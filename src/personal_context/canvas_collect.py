"""Read Canvas with a user-provided API token and ingest complete snapshots."""
import argparse
import base64
from datetime import datetime, timezone
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urljoin, urlsplit, urlencode
import zipfile
import xml.etree.ElementTree as ET
import httpx
from .store import Store

from .canvas_pdf import MAX_FILE_BYTES
from .canvas_modules import CanvasAPIError, collect_course_modules
from .canvas_resources import collect_resources


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []
    def handle_data(self, data): self.parts.append(data)


def plain(value):
    parser = TextParser(); parser.feed(value or '')
    return ' '.join(parser.parts)


class CanvasClient:
    def __init__(self, base_url, token, *, transport=None):
        url = urlsplit(base_url)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
            raise ValueError('Canvas base_url must be an HTTPS origin without credentials')
        if not token or any(c in token for c in '\r\n'):
            raise ValueError('Canvas token is invalid')
        self.base = base_url.rstrip('/')
        self.origin = (url.scheme, url.hostname, url.port or 443)
        self.token = token
        self.http = httpx.Client(timeout=60, follow_redirects=False, transport=transport)

    def close(self): self.http.close()

    def get(self, path):
        url = urljoin(self.base + '/', path)
        if self._origin(url) != self.origin:
            raise ValueError('Canvas request must stay on the configured origin')
        response = self.http.get(url, headers={'Authorization': 'Bearer ' + self.token})
        if response.status_code != 200:
            raise CanvasAPIError(response.status_code)
        item = response.json()
        if not isinstance(item, dict):
            raise ValueError('Canvas returned an invalid record')
        return item

    def _origin(self, url):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.username or parts.password or not parts.hostname:
            raise ValueError('refusing an unsafe Canvas URL')
        return (parts.scheme, parts.hostname, parts.port or 443)

    def pages(self, path, wrapper=None):
        url = urljoin(self.base + '/', path)
        seen = set(); result = []
        while url:
            if self._origin(url) != self.origin:
                raise ValueError('Canvas pagination must stay on the configured origin')
            if url in seen or len(seen) >= 10000:
                raise ValueError('Canvas pagination loop or page limit')
            seen.add(url)
            response = self.http.get(url, headers={'Authorization': 'Bearer ' + self.token})
            if response.status_code != 200:
                raise CanvasAPIError(response.status_code)
            page = response.json()
            if wrapper and isinstance(page, dict):page = page.get(wrapper)
            if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
                raise ValueError('Canvas returned an invalid page')
            result.extend(page)
            next_url = response.links.get('next', {}).get('url')
            url = urljoin(url, next_url) if next_url else None
        return result

    def download(self, url):
        # Canvas can redirect to a signed CDN URL. Never forward the token there.
        url = urljoin(self.base + '/', url)
        for _ in range(5):
            origin = self._origin(url)
            headers = {'Authorization': 'Bearer ' + self.token} if origin == self.origin else {}
            with self.http.stream('GET', url, headers=headers) as response:
                if response.status_code in (301,302,303,307,308):
                    location = response.headers.get('location')
                    if not location: raise ValueError('invalid download redirect')
                    url = urljoin(url, location); continue
                if response.status_code != 200:
                    raise RuntimeError('Canvas file read failed (HTTP %d)' % response.status_code)
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_FILE_BYTES: raise ValueError('Canvas file exceeds size limit')
                return bytes(data)
        raise ValueError('too many file redirects')


def extract(data, filename):
    if filename.lower().endswith('.pdf'):
        result = subprocess.run(['pdftotext', '-', '-'], input=data, capture_output=True, timeout=30)
        if result.returncode: raise ValueError('PDF extraction failed')
        return result.stdout.decode('utf-8', errors='replace')[:1_000_000]
    if filename.lower().endswith('.docx'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo('word/document.xml')
            if info.file_size > 8 * 1024 * 1024: raise ValueError('DOCX XML exceeds size limit')
            doc = ET.fromstring(archive.read(info))
        return '\n'.join(node.text or '' for node in doc.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))[:1_000_000]
    raise ValueError('only PDF and DOCX extraction is supported')


def identifier(item):
    value = item.get('id')
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError('Canvas record has no valid numeric ID')
    return str(value)


def collect_batches(client, account, *, download_files=False, extended=True):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', account): raise ValueError('invalid account label')
    at = datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    courses = client.pages('/api/v1/courses?enrollment_type=student&enrollment_state=active&include[]=total_scores&per_page=100')
    batches = []
    assignments_by_course = {}
    def batch(kind, scope, items):
        batches.append({'schema':1,'source':'canvas-lms','kind':'canvas_' + kind,
            'scope':scope,'collected_at':at,'complete':True,'records':items})
    course_records = []
    for course in courses:
        cid = identifier(course)
        course_records.append({'id':'canvas:'+account+':course:'+cid,
            'title':course.get('name') or '(untitled course)', 'body':plain(course.get('public_description')),
            'payload':course})
    batch('course', account, course_records)
    for course in courses:
        cid = identifier(course); prefix = '/api/v1/courses/' + cid
        scope = account + ':course:' + cid
        for kind, endpoint, title_key, body_key in (
            ('assignment','/assignments?include[]=submission&per_page=100','name','description'),
            ('announcement','/discussion_topics?only_announcements=true&per_page=100','title','message'),
            ('file','/files?per_page=100','display_name',None)):
            records = []
            try:
                source_items = client.pages(prefix + endpoint)
            except CanvasAPIError as exc:
                if kind != 'file' or exc.status not in (403,404):raise
                continue
            if kind == 'assignment':assignments_by_course[int(cid)] = source_items
            for item in source_items:
                rid = identifier(item); payload = dict(item); pdf_data = None
                title = item.get(title_key) or item.get('filename') or '(untitled)'
                body = plain(item.get(body_key)) if body_key else ''
                if kind == 'file':
                    payload['extraction_status'] = 'disabled'
                    payload['pdf_status'] = 'not_archived'
                    filename = item.get('filename') or title
                    if download_files and filename.lower().endswith(('.pdf','.docx')) and item.get('url'):
                        try:
                            data = client.download(item['url'])
                            if filename.lower().endswith('.pdf') and data.startswith(b'%PDF-'):
                                pdf_data = base64.b64encode(data).decode('ascii')
                                payload['pdf_status'] = 'available'
                            body = extract(data, filename)
                            payload['extraction_status'] = 'available' if body.strip() else 'no_text'
                        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, zipfile.BadZipFile, ET.ParseError, httpx.HTTPError):
                            payload['extraction_status'] = 'unavailable'
                records.append({'id':'canvas:'+account+':'+kind+':'+cid+':'+rid,
                    'title':title,'body':body,'start':item.get('due_at') if kind=='assignment' else item.get('posted_at',item.get('created_at')),
                    'payload':payload, **({'pdf_base64': pdf_data} if pdf_data is not None else {})})
            batch(kind,scope,records)

    def read_module(path, params):
        url = '/api/v1/' + path
        if params:
            url += '?' + urlencode(params, doseq=True)
        return client.get(url) if '/pages/' in path else client.pages(url)

    for course, record in zip(courses, course_records):
        try:
            batches.extend(collect_course_modules(read_module, account, course['id'], at))
            record['payload']['module_collection'] = {'status': 'available'}
        except CanvasAPIError as exc:
            if exc.status not in (403, 404):
                raise
            record['payload']['module_collection'] = {'status': 'unavailable', 'http_status': exc.status}

    def read_resource(path, params):
        url = '/api/v1/' + path
        if params:url += '?' + urlencode(params, doseq=True)
        wrapper = 'grading_periods' if path.endswith('/grading_periods') else 'quiz_submissions' if '/quizzes/' in path and path.endswith('/submissions') else None
        single = (path.count('/') == 1 and path.startswith('courses/')) or '/pages/' in path or path.endswith('/front_page') or path.endswith('/submissions/self')
        if single:return client.get(url)
        return client.pages(url, wrapper=wrapper) if wrapper else client.pages(url)

    if extended:
        linked_pages = [b for b in batches if b['kind'] == 'canvas_page']
        batches = [b for b in batches if b['kind'] != 'canvas_page']
        batches.extend(collect_resources(read_resource, account, courses, assignments_by_course, at, linked_pages))

    # Conversation detail reads must explicitly disable Canvas's default
    # auto-mark-as-read behavior so collection remains read-only.
    for scope_name, scope_param in (('inbox', ''), ('archived', '&scope=archived')):
        conversations = client.pages('/api/v1/conversations?per_page=100' + scope_param)
        records = []
        for conversation in conversations:
            cid = identifier(conversation)
            detail = client.get('/api/v1/conversations/%s?auto_mark_as_read=false' % cid)
            messages = []
            bodies = []
            raw_messages = detail.get('messages') or []
            if not isinstance(raw_messages, list):
                raise ValueError('Canvas returned an invalid conversation message list')
            for message in raw_messages:
                if not isinstance(message, dict):
                    raise ValueError('Canvas returned an invalid conversation message')
                message_body = plain(message.get('body'))
                if message_body:
                    bodies.append(message_body)
                messages.append({key: message.get(key) for key in
                                 ('id', 'created_at', 'author_id', 'generated')
                                 if key in message})
                messages[-1]['body'] = message_body
            payload = {key: detail.get(key) for key in (
                'workflow_state', 'last_message_at', 'message_count') if key in detail}
            payload['participants'] = [
                {key: participant.get(key) for key in ('id', 'name', 'full_name') if key in participant}
                for participant in (detail.get('participants') or []) if isinstance(participant, dict)]
            # Store only message fields needed for reading; Canvas may include
            # attachment URLs or other account-specific fields in its response.
            payload['messages'] = messages
            records.append({'id':'canvas:'+account+':conversation:'+cid,
                'title':detail.get('subject') or conversation.get('subject') or '(no subject)',
                'body':'\n\n'.join(bodies), 'start':detail.get('last_message_at') or
                conversation.get('last_message_at'), 'payload':payload})
        batch('conversation', account + ':' + scope_name, records)
    return batches


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--db', required=True)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text())
    token_path = Path(config['token_file']).expanduser()
    if token_path.is_symlink() or token_path.stat().st_mode & 0o077:
        raise ValueError('Canvas token file must be private (mode 0600)')
    if not os.environ.get('PERSONAL_CONTEXT_KEY_FILE'):
        raise ValueError('encrypted archive key is required')
    client = CanvasClient(config['base_url'],token_path.read_text().strip())
    try:
        batches = collect_batches(client,config['account'],download_files=config.get('download_files',False))
    finally:
        client.close()
    store = Store(args.db)
    try:
        for batch in batches: store.ingest(batch)
    finally:
        store.close()
    print(json.dumps({'batches':len(batches),'records':sum(len(b['records']) for b in batches)}))


if __name__ == '__main__': main()
