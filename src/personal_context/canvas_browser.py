"""Read-only Canvas collection using an owner-configured Firefox session.

Session credentials stay in memory and are never written to the archive or logs.
Login/MFA remains interactive in Firefox. No browser state is modified here.
"""
import argparse
from collections import Counter
import ctypes
import ctypes.util
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import struct
from urllib.parse import urlsplit

import httpx

from .canvas_collect import CanvasClient, collect_batches, extract
from .canvas_modules import CanvasAPIError
from .canvas_sync_runner import _partial
from .store import Store

MAX_SESSION_BYTES = 64 * 1024 * 1024


def private_read(path, limit=MAX_SESSION_BYTES):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > limit:
            raise ValueError('Browser configuration/session must be an owner-only regular file')
        data = file.read(limit + 1)
        if len(data) > limit: raise ValueError('Browser session exceeds limit')
        return data


def session_cookies(path, host):
    try:data = private_read(path)
    except FileNotFoundError:raise PermissionError('Open the configured Firefox Canvas session') from None
    if data[:8] != b'mozLz40\0' or len(data) < 12:
        raise ValueError('Invalid Firefox session format')
    length = struct.unpack('<I', data[8:12])[0]
    if not 0 < length <= MAX_SESSION_BYTES: raise ValueError('Invalid Firefox session size')
    library = ctypes.util.find_library('lz4')
    if not library: raise RuntimeError('Local liblz4 is required')
    lib = ctypes.CDLL(library)
    lib.LZ4_decompress_safe.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    lib.LZ4_decompress_safe.restype = ctypes.c_int
    output = ctypes.create_string_buffer(length)
    actual = lib.LZ4_decompress_safe(data[12:], output, len(data)-12, length)
    if actual != length: raise ValueError('Invalid Firefox session compression')
    session = json.loads(output.raw)
    cookies = httpx.Cookies()
    for cookie in session.get('cookies', []):
        # Exact school host only: never load Microsoft, portal, or other-site cookies.
        if cookie.get('host', '').lstrip('.') != host: continue
        attributes = cookie.get('originAttributes', {})
        if not isinstance(attributes, dict) or any(attributes.values()): continue
        cookies.set(cookie['name'], cookie['value'], domain=host, path=cookie.get('path', '/'))
    if not cookies: raise PermissionError('Canvas browser sign-in required')
    return cookies


class BrowserCanvasClient(CanvasClient):
    def __init__(self, base_url, cookies, *, transport=None):
        super().__init__(base_url, 'unused-browser-auth', transport=transport)
        self._download_transport = transport
        self.http.cookies = cookies
        self.http.event_hooks = {'request': [self._guard]}

    def _guard(self, request):
        request.headers.pop('authorization', None)
        if request.method != 'GET' or self._origin(str(request.url)) != self.origin:
            raise ValueError('Browser Canvas access permits same-origin GET only')
        path = request.url.path
        if not path.startswith('/api/v1/') or any(word in path.split('/') for word in ('logout','mark_read','mark_all_as_read','access_tokens')):
            raise ValueError('Browser Canvas access requires a read API route')
        if re.fullmatch(r'/api/v1/conversations/[0-9]+', path):
            if request.url.params.get_list('auto_mark_as_read') != ['false']:
                raise ValueError('Conversation reads must preserve unread state')
        if any(key in request.url.params for key in ('_method', 'method', 'mark_as_read')):
            raise ValueError('Canvas mutation parameters are forbidden')

    def download(self, url):
        # Separate anonymous client for signed file URLs. Session cookies cannot leak
        # to CDN hosts. Only institutional file APIs may use the authenticated client.
        from .canvas_pdf import MAX_FILE_BYTES
        from urllib.parse import urljoin
        current = urljoin(self.base + '/', url)
        with httpx.Client(timeout=60, follow_redirects=False, transport=self._download_transport) as anonymous:
            for _ in range(5):
                parts = urlsplit(current)
                if parts.scheme != 'https' or parts.username or parts.password or parts.port not in (None,443):
                    raise ValueError('Unsafe Canvas file URL')
                same = self._origin(current) == self.origin
                if same:
                    if not re.fullmatch(r'/(?:api/v1/)?files/[0-9]+/(?:download|preview)', parts.path):
                        raise ValueError('Invalid Canvas file route')
                    # Cookies are attached only to this exact-origin file download.
                    request = anonymous.build_request('GET', current)
                    self.http.cookies.set_cookie_header(request)
                else:
                    host = parts.hostname or ''
                    if not (host.endswith('.instructureusercontent.com') or host.endswith('.canvas-user-content.com') or host.endswith('.s3.amazonaws.com')):
                        raise ValueError('Unapproved Canvas file CDN')
                    request = anonymous.build_request('GET', current)
                response = anonymous.send(request, stream=True)
                try:
                    if response.status_code in (301,302,303,307,308):
                        location = response.headers.get('location')
                        if not location: raise ValueError('Invalid file redirect')
                        current = urljoin(current, location); continue
                    if response.status_code != 200: raise CanvasAPIError(response.status_code)
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_FILE_BYTES: raise ValueError('Canvas file exceeds limit')
                    return bytes(data)
                finally: response.close()
        raise ValueError('Too many Canvas file redirects')


def linked_file_batches(client, batches, account):
    """Read observed module File IDs even if the course Files index is disabled."""
    import base64
    from concurrent.futures import ThreadPoolExecutor
    import io
    import zipfile
    import xml.etree.ElementTree as ET
    stamp=batches[0]['collected_at']
    file_batches={b['scope']:b for b in batches if b['kind']=='canvas_file'}
    references=set()
    for batch in batches:
        if batch['kind']!='canvas_module_item':continue
        for record in batch['records']:
            item=record['payload']
            cid,fid=item.get('course_id'),item.get('content_id')
            if item.get('type')=='File' and type(cid) is int and type(fid) is int and cid>0 and fid>0:
                references.add((cid,fid))
    supported={'.pdf','.docx','.pptx','.txt','.md'}
    existing=set()
    for batch in file_batches.values():
        for record in batch['records']:
            item=record['payload'];cid=int(batch['scope'].rsplit(':',1)[1]);fid=item.get('id')
            if type(fid) is int and fid>0:references.add((cid,fid))
            if item.get('extraction_status') in ('available','no_text') or Path(item.get('filename','')).suffix.lower() not in supported:
                existing.add(record['id'])
    references=[(cid,fid) for cid,fid in sorted(references) if f'canvas:{account}:file:{cid}:{fid}' not in existing]
    def read(reference):
        cid,fid=reference
        try:item=client.get(f'/api/v1/courses/{cid}/files/{fid}')
        except CanvasAPIError as exc:
            if exc.status not in (403,404):raise
            return cid,None,{'status':'unavailable','http_status':exc.status}
        if item.get('id')!=fid:raise ValueError('Canvas linked file identity mismatch')
        payload=dict(item,discovered_via='module',extraction_status='disabled',pdf_status='not_archived')
        title=item.get('display_name') or item.get('filename') or '(untitled file)'
        record={'id':f'canvas:{account}:file:{cid}:{fid}','title':title,'body':'','payload':payload}
        filename=item.get('filename') or title
        extension=Path(filename).suffix.lower()
        if extension in ('.pdf','.docx','.pptx','.txt','.md') and item.get('url'):
            try:
                data=client.download(item['url'])
                if extension in ('.pdf','.docx'):body=extract(data,filename)
                elif extension=='.pptx':
                    parts=[];total=0
                    with zipfile.ZipFile(io.BytesIO(data)) as archive:
                        slides=sorted((i for i in archive.infolist() if re.fullmatch(r'ppt/slides/slide[0-9]+\.xml',i.filename)),
                                      key=lambda i:int(re.search(r'slide([0-9]+)',i.filename)[1]))
                        for info in slides:
                            total+=info.file_size
                            if total>8*1024*1024:raise ValueError('Slide text exceeds limit')
                            root=ET.fromstring(archive.read(info))
                            parts.append(' '.join(n.text or '' for n in root.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}t')))
                    body='\n\n'.join(parts)
                else:body=data.decode('utf-8',errors='replace')
                record['body']=body[:1_000_000]
                payload['extraction_status']='available' if body.strip() else 'no_text'
                if extension=='.pdf' and data.startswith(b'%PDF-'):
                    record['pdf_base64']=base64.b64encode(data).decode('ascii');payload['pdf_status']='available'
            except (OSError,ValueError,RuntimeError,httpx.HTTPError,zipfile.BadZipFile,ET.ParseError,subprocess.TimeoutExpired):
                payload['extraction_status']='unavailable'
        return cid,record,{'status':'available'}
    coverage={}
    # Bounded parallel file reads; never model-selected endpoints or arbitrary URLs.
    with ThreadPoolExecutor(max_workers=4) as pool:
        for cid,record,state in pool.map(read,references):
            scope=f'{account}:course:{cid}'
            info=coverage.setdefault(cid,{'status':'available','checked_at':stamp,'available_count':0,'unavailable_count':0})
            if record is None:
                info['status']='partial';info['unavailable_count']+=1;continue
            info['available_count']+=1
            if scope not in file_batches:
                batch={'schema':1,'source':'canvas-lms','kind':'canvas_file','scope':scope,'collected_at':stamp,'complete':False,'records':[]}
                batches.append(batch);file_batches[scope]=batch
            file_batches[scope]['records']=[r for r in file_batches[scope]['records'] if r['id']!=record['id']]
            file_batches[scope]['records'].append(record)
    for batch in batches:
        if batch['kind']=='canvas_collection_state':
            for record in batch['records']:
                cid=record['payload'].get('course_id')
                if cid in coverage:record['payload'].setdefault('features',{})['module_linked_file']=coverage[cid]
    return batches


def load_config(path):
    config = json.loads(private_read(path, 65536))
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', config.get('account', '')):
        raise ValueError('Invalid browser account label')
    url = urlsplit(config.get('base_url',''))
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.port not in (None,443) or url.path not in ('','/') or url.query or url.fragment:
        raise ValueError('Browser Canvas requires an HTTPS origin')
    if not isinstance(config.get('expected_user_id'), int) or isinstance(config['expected_user_id'],bool) or config['expected_user_id'] <= 0:
        raise ValueError('Pinned Canvas user ID required')
    if 'download_files' in config and not isinstance(config['download_files'],bool):
        raise ValueError('download_files must be boolean')
    for field in ('session_file','status_file'):
        if not Path(config.get(field,'')).is_absolute(): raise ValueError('Absolute private paths required')
    return config


def write_status(path, value):
    path = Path(path); path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW, 0o600)
    os.fchmod(fd,0o600)
    with os.fdopen(fd,'w') as file: json.dump(value,file)
    os.replace(temp,path)


def run(config_path, database):
    config = load_config(config_path)
    status_path = Path(config['status_file'])
    status_path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd = os.open(str(status_path)+'.lock', os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return {'state':'running','account':config['account']}
        previous = {}
        if status_path.exists(): previous=json.loads(private_read(status_path,65536))
        status={'account':config['account'],'state':'running','started_at':datetime.now(timezone.utc).isoformat(),
                'last_success_at':previous.get('last_success_at'),'counts':previous.get('counts',{}),
                'authentication':'firefox_session','source_writes':False,'phase':'collecting','requests_completed':0}
        write_status(status_path,status)
        client=None
        try:
            cookies=session_cookies(config['session_file'],urlsplit(config['base_url']).hostname)
            client=BrowserCanvasClient(config['base_url'],cookies)
            import threading
            progress_lock=threading.Lock()
            request_count=0
            def progress(response):
                nonlocal request_count
                with progress_lock:
                    request_count+=1
                    if request_count % 25 == 0:
                        status.update(requests_completed=request_count, heartbeat_at=datetime.now(timezone.utc).isoformat())
                        write_status(status_path,status)
            client.http.event_hooks['response']=[progress]
            profile=client.get('/api/v1/users/self/profile')
            if profile.get('id') != config['expected_user_id']:raise PermissionError('Canvas account mismatch')
            batches=collect_batches(client,config['account'],download_files=config.get('download_files',True),extended=True,include_inactive=True)
            if config.get('download_files',True):
                batches=linked_file_batches(client,batches,config['account'])
            # Collection must finish before touching the archive. Failures retain last snapshot.
            status.update(phase='ingesting',requests_completed=request_count)
            write_status(status_path,status)
            store=Store(database)
            try:
                for batch in batches:store.ingest(batch)
            finally:store.close()
            counts=Counter()
            for batch in batches:counts[batch['kind']]+=len(batch['records'])
            status.update(state='partial' if any(_partial(b) for b in batches) else 'complete',
                          last_success_at=datetime.now(timezone.utc).isoformat(),counts=dict(counts),
                          batches=len(batches),error_code=None)
        except (PermissionError, CanvasAPIError) as exc:
            auth=isinstance(exc,PermissionError) or exc.status in (401,302,303)
            status.update(state='authentication_required' if auth else 'failed',error_code='browser_sign_in_required' if auth else 'canvas_http_error')
        except (OSError,ValueError,RuntimeError,httpx.HTTPError):
            status.update(state='failed',error_code='browser_collection_failed')
        finally:
            if client:client.close()
        status['phase']='finished'
        status['finished_at']=datetime.now(timezone.utc).isoformat()
        write_status(status_path,status)
        return status


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--db',required=True)
    args=parser.parse_args()
    result=run(args.config,args.db);print(json.dumps(result))
    if result['state'] in ('failed','authentication_required'):raise SystemExit(1)


if __name__=='__main__':main()
