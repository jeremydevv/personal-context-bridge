"""Bounded read-only iCloud Drive adapter. Authentication is terminal-only."""
import base64
import codecs
import configparser
import contextlib
import fcntl
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import threading
import time

MAX_OUTPUT = 4 * 1024 * 1024


class DriveError(RuntimeError):
    pass


def normalize_path(path):
    if not isinstance(path, str) or len(path) > 2048 or path.startswith('/') or any(
        c in path for c in (':', '\\')
    ) or any(ord(c) < 32 or ord(c) == 127 for c in path):
        raise ValueError('Expected a relative iCloud Drive path')
    if any(p in ('.', '..', '') for p in path.split('/')) and path:
        raise ValueError('Path traversal and empty path components are forbidden')
    return path


def bound(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be between {low} and {high}')


class Drive:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get('PERSONAL_CONTEXT_ICLOUD_DIR',
                         str(Path.home()/'.local/share/personal-context-icloud'))).absolute()
        self.config = self.root/'rclone.conf'
        self.binary = self.root/'rclone-fido2'
        self.password_command = self.root/'config-password'

    def environment(self):
        return {'HOME': str(Path.home()), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                'PERSONAL_CONTEXT_KEY_FILE': os.environ.get('PERSONAL_CONTEXT_KEY_FILE',
                    f'/run/user/{os.getuid()}/personal-context-bridge.key')}

    def _require_config(self):
        for path in (self.root, self.config):
            try:
                s = path.lstat()
            except OSError:
                raise DriveError('authentication_required: run the local iCloud setup command') from None
            if stat.S_ISLNK(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
                raise DriveError('Private owner-only iCloud configuration required')
        if not self.config.is_file() or self.config.stat().st_size > 1024*1024:
            raise DriveError('Invalid iCloud configuration')
        with self.config.open('rb') as f:
            if b'RCLONE_ENCRYPT_V0:' not in f.read(256):
                raise DriveError('Encrypted iCloud configuration required')

    @contextlib.contextmanager
    def lock(self):
        fd = os.open(self.root/'operation.lock', os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise DriveError('iCloud busy; retry after the current operation finishes') from None
            yield
        finally:
            os.close(fd)

    def _run(self, args, cap=MAX_OUTPUT, timeout=45):
        self._require_config()
        if args[0] not in ('lsjson', 'cat', 'listremotes'):
            raise ValueError('Unsupported read operation')
        command = [str(self.binary), '--config', str(self.config), '--password-command',
                   str(self.password_command), '--ask-password=false', '--iclouddrive-service', 'drive',
                   '--retries', '1', '--low-level-retries', '1', '--contimeout', '10s',
                   '--timeout', '30s', '--log-level', 'ERROR', *args]
        with self.lock():
            if args[0] in ('lsjson', 'cat'):
                check = command[:command.index(args[0])] + ['config', 'redacted', 'icloud']
                redacted = self._execute(check, 65536, 10)
                config = configparser.ConfigParser(interpolation=None)
                try:
                    config.read_string(redacted.decode())
                    valid = config.get('icloud', 'type', fallback='') == 'iclouddrive'
                except (ValueError, UnicodeError, configparser.Error):
                    valid = False
                if not valid:
                    raise DriveError('authentication_required: configure icloud with type iclouddrive locally')
            return self._execute(command, cap, timeout)

    def _execute(self, command, cap, timeout):
        try:
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, env=self.environment(),
                                    start_new_session=True)
        except OSError:
            raise DriveError('iCloud runtime unavailable; inspect the local setup') from None
        expired = threading.Event()
        def kill():
            expired.set()
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        timer = threading.Timer(timeout, kill)
        timer.start()
        try:
            output = proc.stdout.read(cap+1)
            if len(output) > cap:
                kill()
                raise DriveError('iCloud response exceeds the safety bound; narrow the folder or depth')
            code = proc.wait()
            if expired.is_set():
                raise DriveError('iCloud request timed out; narrow the request or check authentication')
            if code:
                raise DriveError('iCloud authentication or provider access failed; reconnect locally if needed')
            return output
        finally:
            timer.cancel()
            if proc.poll() is None: kill()
            proc.wait()
            proc.stdout.close()

    def _json(self, args):
        try: return json.loads(self._run(args))
        except (ValueError, UnicodeError):
            raise DriveError('Invalid bounded provider response') from None

    def status(self, probe=False):
        result = {'source':'icloud_drive', 'read_only':True, 'experimental_fido2':True,
                  'state':'authentication_required', 'authenticated':False,
                  'binary_installed':self.binary.is_file(), 'encrypted_config':False,
                  'live_access_verified':False, 'session_portability_verified':False}
        try: self._require_config()
        except DriveError: return result
        result['encrypted_config'] = True
        if not self.binary.is_file():
            result['state']='runtime_not_ready'
            return result
        try:
            remotes=self._run(['listremotes']).decode().splitlines()
            if 'icloud:' not in remotes: return result
            result['state']='session_configured_unverified'
            if probe:
                self.list('',limit=1)
                result.update(state='connected',authenticated=True,live_access_verified=True,
                              checked_at=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
        except DriveError:
            result['state']='authentication_or_provider_unavailable'
        return result

    def list(self, path='', limit=100, offset=0):
        path=normalize_path(path);bound(limit,1,1000,'limit');bound(offset,0,100000,'offset')
        rows=self._json(['lsjson','icloud:'+path,'--max-depth','1'])
        if not isinstance(rows,list):raise DriveError('Invalid directory response')
        rows.sort(key=lambda r:r.get('Path',''))
        return {'path':path,'items':rows[offset:offset+limit], 'has_more':offset+limit<len(rows),
                'next_offset':offset+limit if offset+limit<len(rows) else None,
                'source_content_untrusted':True}

    def search(self, query, path='', limit=100, offset=0, max_depth=3):
        path=normalize_path(path);bound(limit,1,1000,'limit');bound(offset,0,100000,'offset')
        bound(max_depth,1,10,'max_depth')
        if not isinstance(query,str) or not query.strip() or len(query)>200:
            raise ValueError('Supply a filename query of 1–200 characters')
        rows=self._json(['lsjson','icloud:'+path,'--recursive','--max-depth',str(max_depth)])
        if not isinstance(rows,list):raise DriveError('Invalid search response')
        rows=sorted((r for r in rows if query.casefold() in r.get('Path','').casefold()),
                    key=lambda r:r.get('Path',''))
        return {'path':path,'items':rows[offset:offset+limit],'has_more':offset+limit<len(rows),
                'next_offset':offset+limit if offset+limit<len(rows) else None,
                'match_mode':'filename_substring','max_depth':max_depth,
                'source_content_untrusted':True}

    def info(self, path):
        path=normalize_path(path)
        if not path:raise ValueError('Supply a file or folder path')
        data=self._json(['lsjson','icloud:'+path,'--stat'])
        if not isinstance(data,dict):raise DriveError('Invalid metadata response')
        return data

    def chunk(self, path, offset=0, max_bytes=65536):
        path=normalize_path(path);bound(offset,0,2**53,'offset');bound(max_bytes,1,262144,'max_bytes')
        info=self.info(path)
        if info.get('IsDir') or type(info.get('Size')) is not int or info['Size']<0:
            raise ValueError('A regular file with a known size is required')
        size=info['Size']
        data=b'' if offset>=size else self._run(['cat','icloud:'+path,'--offset',str(offset),
                                               '--count',str(max_bytes)],cap=max_bytes)
        if offset<size and not data:raise DriveError('File changed or empty provider response; inspect again')
        return {'path':path,'offset':offset,'size':size,'data_base64':base64.b64encode(data).decode(),
                'next_offset':offset+len(data),'eof':offset+len(data)>=size,
                'mod_time':info.get('ModTime'),'source_content_untrusted':True}

    def text(self, path, max_bytes=65536):
        bound(max_bytes,1,262144,'max_bytes')
        path=normalize_path(path)
        if Path(path).suffix.lower() not in ('.txt','.md','.csv','.json','.xml','.html','.htm',
                                             '.log','.yaml','.yml','.ics','.vcf','.py','.js','.ts','.css'):
            raise ValueError('Use the chunk tool for binary or unsupported text formats')
        result=self.chunk(path,max_bytes=max_bytes)
        try: result['text']=codecs.getincrementaldecoder('utf-8')().decode(
            base64.b64decode(result.pop('data_base64')), final=result['eof'])
        except UnicodeError:raise ValueError('Not UTF-8 text; use the chunk tool') from None
        result['truncated']=not result['eof']
        return result
