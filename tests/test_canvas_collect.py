import unittest
from unittest.mock import Mock
from personal_context.canvas_collect import CanvasClient, collect_batches

class CanvasCollectorTests(unittest.TestCase):
    def test_complete_course_and_grade_snapshots(self):
        client = Mock()
        client.pages.side_effect = [
            [{'id': 7, 'name': 'Fictional course'}],
            [{'id': 8, 'name': 'Fictional assignment', 'description': '<p>Read chapter</p>',
              'due_at': '2026-01-02T00:00:00Z', 'submission': {'grade': 'A', 'score': 10}}],
            [{'id': 9, 'title': 'Fictional announcement', 'message': '<p>Welcome</p>'}],
            [{'id': 10, 'display_name': 'sample.pdf', 'url': 'https://canvas.example.invalid/file'}], [], []]
        batches = collect_batches(client, 'demo')
        self.assertEqual([x['kind'] for x in batches], ['canvas_course','canvas_assignment','canvas_announcement','canvas_file','canvas_conversation','canvas_conversation'])
        self.assertTrue(all(x['complete'] for x in batches))
        self.assertEqual(batches[1]['records'][0]['payload']['submission']['grade'], 'A')
        self.assertEqual(batches[1]['records'][0]['body'], 'Read chapter')
        self.assertEqual(batches[3]['records'][0]['payload']['extraction_status'], 'disabled')
        client.download.assert_not_called()

    def test_pagination_rejects_token_transfer_to_other_origin(self):
        client = CanvasClient('https://canvas.example.invalid', 'synthetic-token')
        with self.assertRaises(ValueError): client.pages('https://other.example.invalid/api/v1/courses')
        client.close()

    def test_no_partial_complete_snapshot_on_api_error(self):
        client = Mock();client.pages.side_effect = [[{'id': 7, 'name': 'Demo'}], RuntimeError('unavailable')]
        with self.assertRaises(RuntimeError): collect_batches(client, 'demo')

    def test_pages_follow_same_origin_and_detect_loops(self):
        import httpx
        def handler(req):
            self.assertEqual(req.headers['authorization'], 'Bearer synthetic-token')
            if req.url.params.get('page') == '2': return httpx.Response(200,json=[{'id': 2}])
            return httpx.Response(200,json=[{'id': 1}],headers={'link':'<https://canvas.example.invalid/api/v1/courses?page=2>; rel="next"'})
        client = CanvasClient('https://canvas.example.invalid', 'synthetic-token', transport=httpx.MockTransport(handler))
        self.assertEqual(client.pages('/api/v1/courses'), [{'id':1},{'id':2}]);client.close()

    def test_http_and_embedded_credentials_rejected(self):
        for url in ('http://canvas.example.invalid', 'https://name:password@canvas.example.invalid'):
            with self.assertRaises(ValueError): CanvasClient(url, 'synthetic-token')

class CanvasRetirementTests(unittest.TestCase):
    def test_course_removal_retires_announcements_and_scope_count(self):
        from personal_context.store import Store
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'test.sqlite3')
            common = {'schema':1,'source':'canvas-lms','complete':True,'collected_at':'2026-01-01T00:00:00Z'}
            store.ingest(dict(common,kind='canvas_course',scope='demo',records=[{'id':'canvas:demo:course:7','title':'Demo'}]))
            store.ingest(dict(common,kind='canvas_announcement',scope='demo:course:7',records=[{'id':'canvas:demo:announcement:7:9','title':'Fictional announcement'}]))
            store.ingest(dict(common,kind='canvas_course',scope='demo',records=[],collected_at='2026-01-02T00:00:00Z'))
            self.assertEqual(store.search('Fictional'), [])
            self.assertEqual(store.db.execute("SELECT count FROM syncs WHERE kind='canvas_announcement'").fetchone()[0], 0)
            store.close()

    def test_status_sums_announcements_across_courses(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from personal_context.onboarding import initialize
        from personal_context.store import Store
        from personal_context.canvas_mcp_server import register_tools
        functions = {}
        class Registry:
            def tool(self, **kwargs):
                def capture(function):
                    functions[function.__name__] = function
                    return function
                return capture
        with tempfile.TemporaryDirectory() as tmp:
            state = initialize(Path(tmp) / 'runtime')
            store = Store(state['database'], key_file=state['key_file'])
            for course in (7, 8):
                store.ingest({'schema':1,'source':'canvas-lms','kind':'canvas_announcement',
                    'scope':f'demo:course:{course}','collected_at':'2026-01-01T00:00:00Z',
                    'complete':True,'records':[{'id':f'canvas:demo:announcement:{course}:9','title':'Fictional'}]})
            store.close()
            with patch.dict(os.environ, {'PERSONAL_CONTEXT_DB':state['database'], 'PERSONAL_CONTEXT_KEY_FILE':state['key_file']}):
                register_tools(Registry())
                self.assertEqual(functions['canvas_status']()['accounts']['demo']['announcement_count'], 2)
