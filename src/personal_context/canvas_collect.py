"""Read Canvas with a user-provided API token and ingest complete snapshots."""
import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urljoin, urlsplit
import zipfile
import xml.etree.ElementTree as ET
import httpx
from .store import Store

MAX_FILE_BYTES = 16 * 1024 * 1024


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

    def _origin(self, url):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.username or parts.password or not parts.hostname:
            raise ValueError('refusing an unsafe Canvas URL')
        return (parts.scheme, parts.hostname, parts.port or 443)

    def pages(self, path):
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
                raise RuntimeError('Canvas API read failed (HTTP %d)' % response.status_code)
            page = response.json()
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


def collect_batches(client, account, *, download_files=False):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', account): raise ValueError('invalid account label')
    at = datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    courses = client.pages('/api/v1/courses?enrollment_type=student&include[]=total_scores&per_page=100')
    batches = []
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
            for item in client.pages(prefix + endpoint):
                rid = identifier(item); payload = dict(item)
                title = item.get(title_key) or item.get('filename') or '(untitled)'
                body = plain(item.get(body_key)) if body_key else ''
                if kind == 'file':
                    payload['extraction_status'] = 'disabled'
                    if download_files and title.lower().endswith(('.pdf','.docx')) and item.get('url'):
                        try:
                            body = extract(client.download(item['url']), title)
                            payload['extraction_status'] = 'available' if body.strip() else 'no_text'
                        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, zipfile.BadZipFile, ET.ParseError, httpx.HTTPError):
                            payload['extraction_status'] = 'unavailable'
                records.append({'id':'canvas:'+account+':'+kind+':'+cid+':'+rid,
                    'title':title,'body':body,'start':item.get('due_at') if kind=='assignment' else item.get('posted_at',item.get('created_at')),
                    'payload':payload})
            batch(kind,scope,records)
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
