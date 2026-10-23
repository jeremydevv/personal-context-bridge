"""Mac-only native-tag receiver. No credentials, delete, upload or copy fallback.

The receiver is a view of the Mac's synced filesystem, not a claim of cloud
convergence. All path traversal is anchored to descriptors with O_NOFOLLOW.
"""
import base64
import contextlib
import ctypes
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import sys
import unicodedata

MAX_SCAN = 2000
MAX_BYTES = 262144
TAG_ATTRIBUTE = b'com.apple.metadata:_kMDItemUserTags'


class NativeError(RuntimeError):
    pass


def fold(value):
    return unicodedata.normalize('NFKC', value).strip().casefold()


def path_value(value):
    if not isinstance(value,str) or len(value)>2048 or any(ord(c)<32 or ord(c)==127 for c in value):
        raise ValueError('Invalid relative path')
    if value.startswith('/') or ':' in value or '\\' in value or (value and any(p in ('','.','..') for p in value.split('/'))):
        raise ValueError('Invalid relative path')
    return value


def integer(value,low,high):
    if type(value) is not int or not low<=value<=high: raise ValueError('Invalid numeric bound')
    return value


def tag_values(values):
    if not isinstance(values,list) or len(values)>32 or any(not isinstance(t,str) or not 1<=len(t.strip())<=100 or any(ord(c)<32 or ord(c)==127 for c in t) for t in values):
        raise ValueError('Expected at most 32 plain tag names')
    return values


def timestamp(value):
    if not value:return None
    if not isinstance(value,str):raise ValueError('Expected ISO date or timezone-aware timestamp')
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value): value+='T00:00:00+00:00'
        date=datetime.fromisoformat(value.replace('Z','+00:00'))
        if date.tzinfo is None:raise ValueError()
        return date.timestamp()
    except (ValueError,OverflowError):raise ValueError('Expected ISO date or timezone-aware timestamp') from None


def iso(value):return datetime.fromtimestamp(value,timezone.utc).isoformat().replace('+00:00','Z')


class NativeTags:
    """Read/write Finder's native binary-plist user tags on the held descriptor.

    Preserve Finder color suffixes for unchanged tags. Missing xattr means an
    untagged local item; all other errors and malformed metadata deny access.
    """
    def __init__(self):
        if sys.platform!='darwin':raise NativeError('native_mac_required')
        self.lib=ctypes.CDLL(None,use_errno=True)
        self.lib.fgetxattr.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_int]
        self.lib.fgetxattr.restype=ctypes.c_ssize_t
        self.lib.fsetxattr.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_int]
        self.lib.fsetxattr.restype=ctypes.c_int

    def raw(self,fd):
        data=ctypes.create_string_buffer(16384)
        count=self.lib.fgetxattr(fd,TAG_ATTRIBUTE,data,len(data),0,0)
        if count<0:
            if ctypes.get_errno()==errno.ENOATTR:return []
            raise NativeError('access_denied')
        try:
            values=plistlib.loads(data.raw[:count])
            if not isinstance(values,list) or any(not isinstance(t,str) for t in values):raise ValueError()
            tag_values([self.name(t) for t in values])
            return values
        except (ValueError,plistlib.InvalidFileException):raise NativeError('access_denied') from None

    @staticmethod
    def name(value):return re.sub(r'\n[0-7]$','',value)

    def __call__(self,fd):return [self.name(t) for t in self.raw(fd)]

    def set(self,fd,values):
        old={fold(self.name(t)):t for t in self.raw(fd)}
        data=plistlib.dumps([old.get(fold(t),t) for t in tag_values(values)],fmt=plistlib.FMT_BINARY)
        if self.lib.fsetxattr(fd,TAG_ATTRIBUTE,data,len(data),0,0):raise NativeError('native_write_failed')


def exclusive_move(source_fd,source,dest_fd,dest):
    """One exclusive kernel rename. EXDEV/unsupported errors never fall back."""
    lib=ctypes.CDLL(None,use_errno=True)
    if sys.platform=='darwin':
        fn=lib.renameatx_np;flag=4 # RENAME_EXCL
    elif sys.platform.startswith('linux'):
        fn=lib.renameat2;flag=1 # RENAME_NOREPLACE, fictional fixture tests only
    else:raise NativeError('exclusive_move_unavailable')
    fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    fn.restype=ctypes.c_int
    if fn(source_fd,os.fsencode(source),dest_fd,os.fsencode(dest),flag):
        raise NativeError('exclusive_move_refused')


class NativeDrive:
    def __init__(self,root,segments=None,tags=None,writer=False):
        self.writer=writer is True
        self.root=Path(root).absolute()
        if self.root.resolve()!=self.root:raise NativeError('root_must_not_contain_symlinks')
        self.segments=segments if segments is not None else {'drive':''}
        if not isinstance(self.segments,dict) or not self.segments or len(self.segments)>50:raise ValueError('Invalid segments')
        for name,value in self.segments.items():
            if not isinstance(name,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,50}',name):raise ValueError('Invalid segment')
            path_value(value)
        self.tags=tags if tags is not None else NativeTags()

    @contextlib.contextmanager
    def _open(self,path):
        path=path_value(path);fds=[]
        try:
            fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK);fds.append(fd)
            self._allowed(fd)
            parts=path.split('/') if path else []
            for n,part in enumerate(parts):
                flags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK
                if n<len(parts)-1:flags|=os.O_DIRECTORY
                fd=os.open(part,flags,dir_fd=fd);fds.append(fd)
                self._allowed(fd)
            yield fd
        except OSError:raise NativeError('access_denied') from None
        finally:
            for fd in reversed(fds):os.close(fd)

    def _allowed(self,fd):
        s=os.fstat(fd)
        if not (stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)):raise NativeError('access_denied')
        values=tag_values(self.tags(fd))
        if any(fold(t)=='identification' for t in values):raise NativeError('access_denied')
        return values

    def _scope(self,segment,path):
        if segment not in self.segments:raise ValueError('Unknown folder segment')
        path=path_value(path);root=self.segments[segment]
        if root and path!=root and not path.startswith(root+'/'):raise NativeError('access_denied')
        return path

    def _item(self,path,fd):
        tags=self._allowed(fd);s=os.fstat(fd)
        signature=[s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns,sorted(tags)]
        return {'path':path,'name':path.rsplit('/',1)[-1],'is_dir':stat.S_ISDIR(s.st_mode),
                'size':s.st_size,'modified_at':iso(s.st_mtime),'created_at':iso(getattr(s,'st_birthtime',s.st_ctime)),
                'tags':tags,'revision':hashlib.sha256(json.dumps(signature).encode()).hexdigest()}

    def _info(self,path):
        with self._open(path) as fd:return self._item(path,fd)

    def _revision(self,path,revision,fd=None):
        if not isinstance(revision,str) or len(revision)!=64:raise NativeError('revision_required')
        item=self._item(path,fd) if fd is not None else self._info(path)
        if item['revision']!=revision:raise NativeError('revision_changed')
        return item

    def _identity_at(self,path,held):
        """Recheck namespace identity, including after a pathname-based mutation.

        Native rename cannot atomically condition on an inode. Detected changes
        after dispatch must never report completion or trigger a blind rollback.
        """
        expected=os.fstat(held)
        if not path:
            with self._open('') as fd:actual=os.fstat(fd)
        else:
            parent,name=path.rsplit('/',1) if '/' in path else ('',path)
            with self._open(parent) as fd:actual=os.stat(name,dir_fd=fd,follow_symlinks=False)
        if (actual.st_dev,actual.st_ino,stat.S_IFMT(actual.st_mode))!=(expected.st_dev,expected.st_ino,stat.S_IFMT(expected.st_mode)):
            raise NativeError('write_outcome_unconfirmed')

    def _walk(self,folder,depth,strict=False):
        count=0;stack=[(folder,0)];out=[]
        while stack:
            parent,level=stack.pop()
            with self._open(parent) as fd:names=os.listdir(fd)
            for name in names:
                count+=1
                if count>MAX_SCAN:raise NativeError('scan_bound_exceeded_narrow_folder')
                path=parent+'/'+name if parent else name
                try:
                    item=self._info(path)
                    out.append(item)
                    if item['is_dir']:
                        if level+1<depth:stack.append((path,level+1))
                        elif strict:
                            with self._open(path) as child:
                                if os.listdir(child):raise NativeError('subtree_depth_exceeded')
                except (NativeError,ValueError):
                    if strict:raise NativeError('subtree_not_fully_accessible') from None
        return out

    def _search(self,operation,segment,**kw):
        allowed={'folder','query','name','tags','tags_match','extensions','modified_after','modified_before','created_after','created_before','limit','offset','max_depth','sort'}
        if set(kw)-allowed:raise ValueError('Unknown filter')
        base=self.segments[segment]
        folder=kw.get('folder') or base;path_value(folder)
        limit=integer(kw.get('limit',100),1,1000);offset=integer(kw.get('offset',0),0,100000)
        depth=integer(kw.get('max_depth',3),1,10) if operation=='search' else 1
        tags=tag_values(kw.get('tags',[]));mode=kw.get('tags_match','all')
        if mode not in ('all','any'):raise ValueError('Invalid tag matching')
        sort=kw.get('sort','newest')
        if sort not in ('newest','oldest','name'):raise ValueError('Invalid sort')
        query=kw.get('query','');name=kw.get('name','');extensions=kw.get('extensions',[])
        if any(not isinstance(t,str) or len(t)>200 for t in (query,name)):raise ValueError('Invalid name filter')
        if not isinstance(extensions,list) or len(extensions)>32 or any(not isinstance(e,str) or not re.fullmatch(r'\.?[a-zA-Z0-9]{1,20}',e) for e in extensions):raise ValueError('Invalid extension filter')
        dates={k:timestamp(kw.get(k,'')) for k in ('modified_after','modified_before','created_after','created_before')}
        if base and folder!=base and not folder.startswith(base+'/'):rows=[]
        else:rows=self._walk(folder,depth)
        def matches(item):
            if fold(query) not in fold(item['path']) or fold(name) not in fold(item['name']):return False
            present={fold(t) for t in item['tags']};requested={fold(t) for t in tags}
            if requested and not (requested<=present if mode=='all' else requested&present):return False
            if extensions and (item['is_dir'] or Path(item['path']).suffix.casefold().lstrip('.') not in {e.casefold().lstrip('.') for e in extensions}):return False
            for field in ('modified','created'):
                value=timestamp(item[field+'_at']);after=dates[field+'_after'];before=dates[field+'_before']
                if after is not None and value<after or before is not None and value>=before:return False
            return True
        rows=[r for r in rows if matches(r)]
        rows.sort(key=lambda r:r['path'].casefold())
        if sort!='name':rows.sort(key=lambda r:timestamp(r['modified_at']),reverse=sort=='newest')
        # Recheck all visible paths before returning. No plaintext index/cache.
        selected=[self._revision(r['path'],r['revision']) for r in rows[offset:offset+limit]]
        return {'items':selected,'segment':segment,'folder':folder,'sort':sort,'has_more':offset+limit<len(rows),
                'next_offset':offset+limit if offset+limit<len(rows) else None,'source_content_untrusted':True,
                'metadata_authority':'mac_synced_native_finder_tags'}

    @staticmethod
    def _read_bytes(fd,offset,count):
        return os.pread(fd,count,offset)

    def dispatch(self,request):
        if not isinstance(request,dict):raise ValueError('Expected object')
        request=request.copy();operation=request.pop('operation',None);segment=request.pop('segment','drive')
        if operation=='status':
            return {'state':'native_receiver_ready','native_tags':True,'writer_operations':['tag','mkdir','move'],
                    'delete_allowed':False,'live_access_verified':False,'writer_enabled':self.writer}
        if segment not in self.segments:raise ValueError('Unknown folder segment')
        if operation=='segments':
            visible=[]
            for name,path in self.segments.items():
                try:self._info(path)
                except (NativeError,OSError,ValueError):continue
                visible.append({'name':name,'folder':path})
            return {'segments':visible}
        if operation in ('list','search'):return self._search(operation,segment,**request)
        if operation not in ('info','read','tag','mkdir','move'):raise ValueError('Unsupported operation')
        path=self._scope(segment,request.get('path',''))
        if operation=='info':return self._info(path)
        if operation=='read':
            offset=integer(request.get('offset',0),0,2**53);count=integer(request.get('max_bytes',65536),1,MAX_BYTES)
            with self._open(path) as fd:
                item=self._item(path,fd)
                if item['is_dir']:raise NativeError('regular_file_required')
                if request.get('revision'):self._revision(path,request['revision'],fd)
                data=self._read_bytes(fd,offset,count)
                self._revision(path,item['revision'],fd);self._revision(path,item['revision'])
            return {'path':path,'data_base64':base64.b64encode(data).decode(),'offset':offset,'size':item['size'],
                    'next_offset':offset+len(data),'eof':offset+len(data)>=item['size'],
                    'revision':item['revision'],'mod_time':item['modified_at'],'source_content_untrusted':True}
        if not self.writer:raise NativeError('writer_permission_required')
        if not path:raise NativeError('root_write_forbidden')
        parent,name=path.rsplit('/',1) if '/' in path else ('',path)
        self._scope(segment,parent)
        if operation=='mkdir':
            with self._open(parent) as fd:
                self._revision(parent,request.get('revision'),fd)
                self._identity_at(parent,fd)
                os.mkdir(name,mode=0o700,dir_fd=fd)
                self._identity_at(parent,fd)
            return {'state':'completed','item':self._info(path)}
        with self._open(path) as source:
            item=self._revision(path,request.get('revision'),source)
            if operation=='tag':
                add=tag_values(request.get('add',[]));remove=tag_values(request.get('remove',[]))
                if not add and not remove:raise ValueError('Supply tag additions or removals')
                if any(fold(t)=='identification' for t in remove):raise ValueError('Protected tag removal forbidden')
                if {fold(t) for t in add}&{fold(t) for t in remove}:raise ValueError('Conflicting tags')
                values=[t for t in item['tags'] if fold(t) not in {fold(v) for v in remove}]
                for tag in add:
                    if fold(tag) not in {fold(v) for v in values}:values.append(tag.strip())
                tag_values(values);self._revision(path,item['revision'])
                self.tags.set(source,values)
                self._identity_at(path,source)
                if {fold(t) for t in self.tags(source)}!={fold(t) for t in values}:raise NativeError('write_outcome_unconfirmed')
                if any(fold(t)=='identification' for t in values):return {'state':'completed','now_protected':True}
                return {'state':'completed','item':self._info(path)}
            destination=self._scope(segment,request.get('destination',''))
            if not destination or destination==path or destination.startswith(path+'/'):raise ValueError('Invalid destination')
            dest_parent,dest_name=destination.rsplit('/',1) if '/' in destination else ('',destination)
            self._scope(segment,dest_parent)
            if item['is_dir']:raise NativeError('file_moves_only')
            with self._open(parent) as from_fd,self._open(dest_parent) as to_fd:
                self._revision(dest_parent,request.get('destination_revision'),to_fd)
                self._identity_at(parent,from_fd);self._identity_at(dest_parent,to_fd)
                self._revision(path,item['revision']);self._revision(path,item['revision'],source)
                exclusive_move(from_fd,name,to_fd,dest_name)
                self._identity_at(parent,from_fd);self._identity_at(dest_parent,to_fd)
                self._identity_at(destination,source)
            return {'state':'completed','item':self._info(destination)}


def main():
    """Fixed SSH endpoint; config is local admin-controlled, never supplied by MCP."""
    try:
        config=Path.home()/'.config/personal-context-bridge/icloud-native.json'
        s=config.lstat()
        if stat.S_ISLNK(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>16384:raise NativeError('private_config_required')
        cfg=json.loads(config.read_text())
        if cfg.get('enabled') is not True:raise NativeError('native_connection_not_enabled')
        drive=NativeDrive(cfg['root'],cfg.get('segments'),writer=cfg.get('permission')=='writer')
        raw=sys.stdin.buffer.read(16385)
        if len(raw)>16384:raise ValueError('request_bound')
        # Serialize our own receiver requests, never replay a failed writer.
        lock=config.with_suffix('.lock')
        fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=drive.dispatch(json.loads(raw))
        print(json.dumps({'ok':True,'result':result},ensure_ascii=True))
    except (NativeError,OSError,ValueError,KeyError,TypeError):
        # Do not expose native paths, raw filesystem exceptions or tag data on failures.
        print(json.dumps({'ok':False,'error':'native_access_denied_or_unavailable'}))


if __name__=='__main__':main()
