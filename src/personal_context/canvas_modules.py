"""Shared read-only module snapshots for portable and Mac Canvas collectors."""
from html.parser import HTMLParser
import re
from urllib.parse import quote


class CanvasAPIError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__('Canvas API read failed (HTTP %d)' % status)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)


def _plain(value):
    parser = _Text()
    parser.feed(value or '')
    return ' '.join(parser.parts)


def _id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError('Canvas module content requires positive numeric IDs')
    return str(value)


def _list(value):
    if not isinstance(value, list) or len(value) > 10000 or any(not isinstance(v, dict) for v in value):
        raise ValueError('Canvas module list is invalid or too large')
    ids = [_id(v.get('id')) for v in value]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate Canvas module/item ID')
    for v in value:
        if isinstance(v.get('position', 0), bool) or not isinstance(v.get('position', 0), int):
            raise ValueError('invalid Canvas module/item position')
    return sorted(value, key=lambda v: (v.get('position', 0), v['id']))


def collect_course_modules(read, account, course_id, stamp):
    """read(path, params) must paginate lists and preserve same-origin token safety.

    Permission/not-found errors on modules/items propagate so callers can mark
    that course unavailable without inventing an authoritative empty snapshot.
    Linked locked pages retain metadata with explicit unavailable content.
    """
    if not re.fullmatch(r'[A-Za-z0-9_-]+', account):
        raise ValueError('invalid Canvas account label')
    cid = _id(course_id)
    prefix = 'courses/' + cid
    record_prefix = 'canvas:' + account + ':'
    modules, items, pages = [], [], {}
    for module in _list(read(prefix + '/modules', {'per_page': 100})):
        mid = _id(module['id'])
        payload = {k: v for k, v in module.items() if k != 'items'}
        payload.update(account=account, course_id=course_id)
        modules.append({'id': record_prefix + 'module:' + cid + ':' + mid,
                        'title': str(module.get('name') or '(untitled module)'),
                        'body': '', 'payload': payload})
        # Never rely on include[]=items: Canvas may omit or truncate it.
        for item in _list(read(prefix + '/modules/' + mid + '/items',
                               {'per_page': 100, 'include[]': ['content_details']})):
            iid = _id(item['id'])
            if item.get('module_id', module['id']) != module['id']:
                raise ValueError('Canvas item belongs to another module')
            detail = dict(item, account=account, course_id=course_id, module_id=module['id'])
            item_type = item.get('type')
            if item_type == 'Page':
                slug = item.get('page_url')
                if not isinstance(slug, str) or not slug or slug in ('.', '..') or len(slug) > 1024:
                    raise ValueError('Canvas module page has no valid locator')
                encoded = quote(slug, safe='')
                page_record_id = record_prefix + 'page:' + cid + ':' + encoded
                detail['linked_record_id'] = page_record_id
                if slug not in pages:
                    try:
                        page = read(prefix + '/pages/' + encoded, {})
                        if not isinstance(page, dict):
                            raise ValueError('invalid Canvas page record')
                        page = dict(page, content_status='available')
                        if page.get('locked_for_user'):
                            page['content_status'] = 'locked'
                    except CanvasAPIError as exc:
                        if exc.status not in (403, 404):
                            raise
                        page = {'title': item.get('title'), 'url': slug,
                                'content_status': 'unavailable', 'http_status': exc.status}
                    html = page.get('body') or ''
                    if not isinstance(html, str) or len(html) > 1_000_000:
                        raise ValueError('Canvas page body is invalid or too large')
                    page.update(account=account, course_id=course_id)
                    pages[slug] = {'id': page_record_id,
                                   'title': str(page.get('title') or item.get('title') or '(untitled page)'),
                                   'body': _plain(html), 'payload': page}
            elif item_type in ('Assignment', 'File') and item.get('content_id') is not None:
                detail['linked_record_id'] = (record_prefix + item_type.lower() + ':' + cid
                                               + ':' + _id(item['content_id']))
            items.append({'id': record_prefix + 'module_item:' + cid + ':' + mid + ':' + iid,
                          'title': str(item.get('title') or '(untitled item)'),
                          'body': '', 'payload': detail})
    return [{'schema': 1, 'source': 'canvas-lms', 'kind': 'canvas_' + kind,
             'scope': account + ':course:' + cid, 'collected_at': stamp,
             'complete': True, 'records': records}
            for kind, records in [('module', modules), ('module_item', items), ('page', list(pages.values()))]]
