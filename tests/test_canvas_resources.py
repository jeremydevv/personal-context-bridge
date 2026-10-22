"""Fictional coverage, permission and encrypted retrieval tests."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from personal_context import canvas_resources as resources
from personal_context.canvas_modules import CanvasAPIError
from personal_context.canvas_mcp_server import register_tools
from personal_context.store import Store

STAMP = '2026-01-01T00:00:00Z'

class CanvasResourcesTests(unittest.TestCase):
    def collect(self, denied=(), error=None):
        self.calls = []
        def read(path, params=None, **kwargs):
            self.calls.append((path, params))
            if path in denied:
                raise CanvasAPIError(403)
            if path == error:
                raise CanvasAPIError(503)
            data = {
                'courses/7': {'id':7,'syllabus_body':'<p>Fictional syllabus</p>'},
                'courses/7/pages': [{'page_id':31,'url':'outside-module','title':'Extra lesson'}],
                'courses/7/pages/outside-module': {'page_id':31,'url':'outside-module','title':'Extra lesson','body':'<p>Fictional extra content</p>'},
                'courses/7/front_page': {'page_id':32,'url':'welcome','title':'Welcome','body':'<p>Front page text</p>'},
                'courses/7/discussion_topics': [{'id':40,'title':'Discuss','message':'<p>Discuss atoms</p>'}],
                'courses/7/discussion_topics/40/entries': [{'id':41,'message':'Atoms are small','has_more_replies':True,'recent_replies':[{'id':42,'message':'Nested reply'}]}],
                'courses/7/discussion_topics/40/entries/41/replies': [{'id':42,'message':'Nested reply'},{'id':43,'message':'Older reply'}],
                'courses/7/assignments/8/submissions/self': {'id':50,'body':'<p>My answer</p>','submission_comments':[{'id':51,'comment':'Explain your reasoning'}],'submission_history':[{'attempt':1,'body':'Earlier answer'}],'rubric_assessment':{'criterion':{'points':2}}},
                'courses/7/assignment_groups': [{'id':60,'name':'Practice','group_weight':30,'rules':{'drop_lowest':1}}],
                'courses/7/grading_periods': {'grading_periods':[{'id':61,'title':'Term one'}]},
                'courses/7/grading_standards': [{'id':62,'title':'Letters','grading_scheme':[{'name':'A','value':0.9}]}],
                'courses/7/files': [{'id':63,'display_name':'unlinked.pdf','url':'https://external.example.invalid/signed'}],
                'courses/7/folders': [{'id':64,'name':'Resources'}],
                'courses/7/sections': [{'id':65,'name':'Section A'}],
                'courses/7/users': [{'id':66,'name':'Fictional student'}],
                'courses/7/tabs': [{'id':'modules','label':'Modules'}],
                'courses/7/quizzes': [],
                'planner/items': [{'plannable_date':STAMP,'plannable_id':8,'plannable_type':'assignment','course_id':7,'plannable':{'id':8,'title':'Study'},'planner_override':{'marked_complete':True}}],
                'planner_notes': [{'id':70,'title':'Review','details':'Review atoms','todo_date':STAMP}],
                'planner/overrides': [{'id':71,'plannable_id':8,'marked_complete':True}],
                'users/self/todo': [{'type':'submitting','assignment':{'id':8,'name':'Practice','course_id':7}}],
                'users/self/missing_submissions': [{'id':8,'name':'Practice','course_id':7}],
                'users/self/groups': [{'id':72,'name':'Lab partners'}],
                'calendar_events': [{'id':73,'title':'Office hours','start_at':STAMP}],
            }
            return data.get(path, [])
        batches = resources.collect_resources(read,'demo',[{'id':7}],{7:[{'id':8}]},STAMP)
        self.assertFalse(any('external.example' in path for path, _ in self.calls))
        return batches

    def test_collects_feedback_discussions_and_full_page_content(self):
        batches = self.collect()
        rows = {b['kind']:b['records'] for b in batches}
        self.assertIn('Explain your reasoning',rows['canvas_submission'][0]['body'])
        self.assertIn('Earlier answer',rows['canvas_submission'][0]['body'])
        self.assertEqual(rows['canvas_submission'][0]['payload']['rubric_assessment']['criterion']['points'],2)
        self.assertEqual(len(rows['canvas_discussion_entry']),3)
        self.assertIn('Older reply',[r['body'] for r in rows['canvas_discussion_entry']])
        self.assertEqual({p['id'] for p in rows['canvas_page']},{'canvas:demo:page:7:outside-module','canvas:demo:page:7:welcome'})
        self.assertIn('Fictional syllabus',rows['canvas_syllabus'][0]['body'])
        self.assertEqual(rows['canvas_assignment_group'][0]['payload']['rules'],{'drop_lowest':1})
        self.assertEqual(rows['canvas_grading_period'][0]['title'],'Term one')
        self.assertTrue(rows['canvas_planner_item'][0]['payload']['planner_override']['marked_complete'])

    def test_permission_failure_preserves_previous_scope_and_explains_coverage(self):
        batches = self.collect(denied=('courses/7/files','courses/7/discussion_topics/40/entries'))
        by_kind = {b['kind']:b for b in batches if b['scope']=='demo:course:7'}
        self.assertNotIn('canvas_file_inventory',by_kind)
        self.assertFalse(by_kind['canvas_discussion_entry']['complete'])
        state = by_kind['canvas_collection_state']['records'][0]['payload']['features']
        self.assertEqual(state['file_inventory']['status'],'unavailable')
        self.assertEqual(state['discussion_entry']['status'],'partial')

    def test_unexpected_error_aborts_without_returning_partial_snapshots(self):
        with self.assertRaises(CanvasAPIError):
            self.collect(error='courses/7/files')

    def test_window_coverage_and_status_are_explicit(self):
        batches = self.collect()
        item = next(b for b in batches if b['kind']=='canvas_planner_item')
        self.assertFalse(item['complete'])
        state = next(b for b in batches if b['kind']=='canvas_collection_state' and b['scope']=='demo')
        feature = state['records'][0]['payload']['features']['planner_item']
        self.assertIn('start',feature['window'])
        self.assertEqual(feature['status'],'available')

    def test_encrypted_mcp_lists_filters_searches_and_retires_new_course_kinds(self):
        functions={}
        class Registry:
            def tool(self,**kwargs):
                def capture(fn):functions[fn.__name__]=fn;return fn
                return capture
        with tempfile.TemporaryDirectory() as tmp:
            key=Path(tmp)/'key';key.write_bytes(os.urandom(32));key.chmod(0o600)
            db=Path(tmp)/'archive.db';store=Store(db,key_file=key)
            common=dict(schema=1,source='canvas-lms',kind='canvas_course',scope='demo',collected_at=STAMP,complete=True)
            store.ingest(dict(common,records=[{'id':'canvas:demo:course:7','title':'Fictional'}]))
            for batch in self.collect():store.ingest(batch)
            store.close()
            with patch.dict(os.environ,PERSONAL_CONTEXT_DB=str(db),PERSONAL_CONTEXT_KEY_FILE=str(key),PERSONAL_CONTEXT_SUMMARIES_DB=str(Path(tmp)/'summaries.db')):
                register_tools(Registry())
                result=functions['list_canvas_records']('discussion_entry',account='demo',course_record_id='canvas:demo:course:7',limit=1,offset=1)
                self.assertEqual(result['total'],3)
                self.assertEqual(len(result['results']),1)
                self.assertEqual(result['collection_status']['features']['discussion_entry']['status'],'available')
                self.assertEqual(len(functions['search_canvas']('reasoning',kind='submission')['results']),1)
                self.assertIsNotNone(functions['get_canvas_record']('grading_period','canvas:demo:grading_period:7:61')['record'])
                self.assertEqual(functions['canvas_status']()['accounts']['demo']['submission_count'],1)
                self.assertIn('canvas_search_explanations',functions)
                self.assertEqual(functions['canvas_summary_status']()['new_canvas_processing'],'paused_until_wifi')
            store=Store(db,key_file=key)
            store.ingest(dict(common,collected_at='2026-01-02T00:00:00Z',records=[]))
            self.assertEqual(store.search('reasoning','canvas_submission'),[])
            self.assertTrue(store.search('Review','canvas_planner_note'))
            store.close()

    def test_summary_inputs_preserve_canvas_metadata_and_hold_new_kinds(self):
        self.assertEqual(resources.summary_kinds(),())
        with patch.dict(os.environ,PERSONAL_CONTEXT_CANVAS_EXTENDED_SUMMARIES='1'):
            self.assertIn('canvas_module',resources.summary_kinds())
            self.assertIn('canvas_submission',resources.summary_kinds())
        self.assertIn('rules',resources.SUMMARY_METADATA_KEYS)
        self.assertIn('completion_requirement',resources.SUMMARY_METADATA_KEYS)

    def test_canvas_explanations_use_existing_summary_results_and_keep_cursors(self):
        import sys,types
        functions={}
        class Registry:
            def tool(self,**kwargs):
                def capture(fn):functions[fn.__name__]=fn;return fn
                return capture
        fake=types.ModuleType('personal_context.summary_mcp')
        def query(operation,**kwargs):
            if operation=='get':return {'found':True,'summary':{'id':kwargs['id'],'source':'canvas_submission','refs':[{'id':'canvas:demo:submission:7:8'}]}}
            if operation=='evidence':return {'found':True,'items':[{'index':0}],'eof':True}
            self.assertEqual(operation,'search')
            return {'summaries':[{'id':'fictional-summary','source':kwargs['source'],'value':{'facts':[]}}],
                    'has_more':True,'next_offset':kwargs['offset']+kwargs['limit']}
        fake.query=query
        with patch.dict(sys.modules,{'personal_context.summary_mcp':fake}):
            register_tools(Registry())
            results=functions['canvas_search_explanations']('atoms',offset=10)
            self.assertIn('canvas_submission',results['by_source'])
            self.assertEqual(results['by_source']['canvas_submission']['summaries'][0]['id'],'fictional-summary')
            self.assertEqual(results['by_source']['canvas_submission']['next_offset'],15)
            detail=functions['get_canvas_explanation']('fictional-summary')
            self.assertEqual(detail['summary']['refs'][0]['id'],'canvas:demo:submission:7:8')
            self.assertTrue(detail['evidence']['eof'])

    def test_wrapped_pagination_and_extended_portable_collection(self):
        import httpx
        from personal_context.canvas_collect import CanvasClient,collect_batches
        paths=[]
        def respond(req):
            self.assertEqual(req.method,'GET');self.assertEqual(req.url.host,'canvas.example.invalid')
            path=req.url.path;paths.append(path)
            if path=='/api/v1/courses':
                self.assertEqual(req.url.params.get('enrollment_state'),'active')
                data=[{'id':7,'name':'Fictional course'}]
            elif path=='/api/v1/courses/7':data={'id':7,'syllabus_body':'Read carefully'}
            elif path.endswith('/grading_periods'):
                if req.url.params.get('page')=='2':data={'grading_periods':[{'id':92,'title':'Second term'}]}
                else:return httpx.Response(200,json={'grading_periods':[{'id':91,'title':'First term'}]},headers={'link':'<https://canvas.example.invalid/api/v1/courses/7/grading_periods?page=2>; rel="next"'})
            elif path.endswith('/front_page'):return httpx.Response(404,json={})
            else:data=[]
            return httpx.Response(200,json=data)
        client=CanvasClient('https://canvas.example.invalid','fictional',transport=httpx.MockTransport(respond))
        try:batches=collect_batches(client,'demo')
        finally:client.close()
        periods=next(b for b in batches if b['kind']=='canvas_grading_period')['records']
        self.assertEqual(len(periods),2)
        self.assertTrue(any(b['kind']=='canvas_planner_note' for b in batches))

    def test_windowed_snapshot_retires_only_missing_records_inside_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'archive.db')
            common=dict(schema=1,source='canvas-lms',kind='canvas_planner_item',scope='demo',complete=False)
            records=[dict(id='canvas:demo:planner_item:'+name,title=name,start=start)
                     for name,start in [('old','2025-01-01T00:00:00Z'),('inside','2026-01-01T00:00:00Z')]]
            store.ingest(dict(common,records=records,collected_at=STAMP))
            store.ingest(dict(common,records=[],collected_at='2026-01-02T00:00:00Z',
                              canvas_window={'start':'2025-12-01T00:00:00Z','end':'2026-06-01T00:00:00Z'}))
            self.assertIsNone(store.get('canvas_planner_item','canvas:demo:planner_item:inside'))
            self.assertIsNotNone(store.get('canvas_planner_item','canvas:demo:planner_item:old'))
            with self.assertRaises(ValueError):
                store.ingest(dict(common,records=[],collected_at=STAMP,canvas_window={'start':'bad','end':'bad'}))
            store.close()

if __name__=='__main__':unittest.main()
