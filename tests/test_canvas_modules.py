"""Fictional end-to-end Canvas module snapshots and MCP retrieval."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from personal_context.canvas_collect import CanvasClient, collect_batches
from personal_context.canvas_mcp_server import register_tools
from personal_context.store import Store


class CanvasModuleTests(unittest.TestCase):
    def collect(self, failure=None):
        self.requests = []
        def handle(req):
            self.requests.append(str(req.url))
            self.assertEqual(req.method, 'GET')
            self.assertEqual(req.url.host, 'canvas.example.invalid')
            p = req.url.path
            if failure and failure in p:
                return httpx.Response(403, json={'error': 'denied'})
            if p == '/api/v1/courses':
                data = [{'id': 7, 'name': 'Fictional course'}]
            elif p.endswith('/modules'):
                data = [{'id': 20, 'name': 'Second', 'position': 2, 'items_count': 0},
                        {'id': 10, 'name': 'First', 'position': 1, 'items_count': 3,
                         'state': 'started', 'prerequisite_module_ids': [20]}]
            elif p.endswith('/modules/20/items'):
                data = []
            elif p.endswith('/modules/10/items'):
                if req.url.params.get('page') == '2':
                    data = [{'id': 103, 'module_id': 10, 'position': 3,
                             'title': 'Elsewhere', 'type': 'ExternalUrl',
                             'external_url': 'https://other.example.invalid/secret'}]
                else:
                    return httpx.Response(200, json=[
                        {'id': 102, 'module_id': 10, 'position': 2, 'indent': 1,
                         'title': 'Practice', 'type': 'Assignment', 'content_id': 8,
                         'completion_requirement': {'type': 'must_submit', 'completed': False}},
                        {'id': 101, 'module_id': 10, 'position': 1, 'title': 'Read this',
                         'type': 'Page', 'page_url': 'lesson-one'}], headers={
                         'link': '<https://canvas.example.invalid/api/v1/courses/7/modules/10/items?page=2>; rel="next"'})
            elif p.endswith('/pages/lesson-one'):
                data = {'page_id': 55, 'url': 'lesson-one', 'title': 'Lesson',
                        'body': '<p>Fictional mitochondria explanation</p>', 'locked_for_user': False}
            else:
                data = []
            return httpx.Response(200, json=data)
        client = CanvasClient('https://canvas.example.invalid', 'fictional-token',
                              transport=httpx.MockTransport(handle))
        try:
            return collect_batches(client, 'demo')
        finally:
            client.close()

    def test_collects_paginated_ordered_modules_items_pages_and_links(self):
        batches = self.collect()
        by_kind = {b['kind']: b for b in batches}
        self.assertIn('canvas_module', by_kind)
        modules = by_kind['canvas_module']['records']
        self.assertEqual([r['payload']['position'] for r in modules], [1, 2])
        self.assertEqual(modules[0]['payload']['state'], 'started')
        items = by_kind['canvas_module_item']['records']
        self.assertEqual([r['id'] for r in items], [
            'canvas:demo:module_item:7:10:101', 'canvas:demo:module_item:7:10:102',
            'canvas:demo:module_item:7:10:103'])
        self.assertEqual(items[1]['payload']['linked_record_id'], 'canvas:demo:assignment:7:8')
        self.assertFalse(items[1]['payload']['completion_requirement']['completed'])
        self.assertEqual(items[0]['payload']['linked_record_id'], 'canvas:demo:page:7:lesson-one')
        self.assertEqual(by_kind['canvas_page']['records'][0]['body'], 'Fictional mitochondria explanation')
        self.assertTrue(all(b['complete'] for b in batches))
        self.assertFalse(any('other.example.invalid' in u for u in self.requests))

    def test_denied_modules_do_not_invent_an_empty_complete_snapshot(self):
        for endpoint in ('/modules', '/modules/10/items'):
            with self.subTest(endpoint=endpoint):
                batches = self.collect(failure=endpoint)
                self.assertFalse(any(b['kind'] == 'canvas_module' for b in batches))
                self.assertEqual(batches[0]['records'][0]['payload']['module_collection'],
                                 {'status': 'unavailable', 'http_status': 403})

    def test_denied_page_has_explicit_unavailable_content(self):
        batches = self.collect(failure='/pages/lesson-one')
        page = next(b for b in batches if b['kind'] == 'canvas_page')['records'][0]
        self.assertEqual(page['body'], '')
        self.assertEqual(page['payload']['content_status'], 'unavailable')
        self.assertEqual(page['payload']['http_status'], 403)

    def test_encrypted_archive_mcp_order_search_pagination_and_retirement(self):
        functions = {}
        class Registry:
            def tool(self, **kwargs):
                def capture(fn):
                    functions[fn.__name__] = fn
                    return fn
                return capture
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp)/'key'; key.write_bytes(os.urandom(32)); key.chmod(0o600)
            db = Path(tmp)/'archive.db'
            store = Store(db, key_file=key)
            batches = self.collect()
            for b in batches: store.ingest(b)
            store.close()
            with patch.dict(os.environ, {'PERSONAL_CONTEXT_DB': str(db), 'PERSONAL_CONTEXT_KEY_FILE': str(key)}):
                register_tools(Registry())
                self.assertIn('canvas_modules', functions)
                modules = functions['canvas_modules']('canvas:demo:course:7')['results']
                self.assertEqual([m['id'] for m in modules], ['canvas:demo:module:7:10', 'canvas:demo:module:7:20'])
                items = functions['canvas_module_items']('canvas:demo:module:7:10', limit=1, offset=1)
                self.assertEqual(items['total'], 3)
                self.assertEqual(items['results'][0]['payload']['content_id'], 8)
                self.assertEqual(functions['canvas_status']()['accounts']['demo']['module_item_count'], 3)
                self.assertEqual(len(functions['search_canvas']('mitochondria',kind='page')['results']), 1)
                page = functions['get_canvas_record']('page','canvas:demo:page:7:lesson-one')['record']
                self.assertEqual(page['payload']['body'], '<p>Fictional mitochondria explanation</p>')
                for bad in ('canvas:demo:module:7:10', 'canvas:demo:course:7junk', 'canvas:demo:course:0'):
                    with self.assertRaises(ValueError): functions['canvas_modules'](bad)
            store = Store(db, key_file=key)
            common = dict(schema=1,source='canvas-lms',scope='demo:course:7',
                          collected_at='2099-01-01T00:00:00Z',complete=True,records=[])
            for kind in ('canvas_module','canvas_module_item','canvas_page'):
                store.ingest(dict(common,kind=kind))
                self.assertEqual(store.search('Fictional',kind), [])
            # Rehydrate, then removal of the course must retire every new kind.
            for b in batches:
                store.ingest(dict(b,collected_at='2099-01-02T00:00:00Z'))
            store.ingest(dict(common,kind='canvas_course',scope='demo',collected_at='2099-01-03T00:00:00Z'))
            for kind in ('canvas_module','canvas_module_item','canvas_page'):
                self.assertEqual(store.db.execute('SELECT COUNT(*) FROM records WHERE kind=? AND deleted=0',(kind,)).fetchone()[0],0)
            store.close()
