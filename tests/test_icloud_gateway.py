import base64
import os
import unittest
from unittest.mock import patch
from personal_context.icloud_gateway import Drive
from personal_context.icloud_drive import DriveError


class GatewayTests(unittest.TestCase):
    def test_fail_closed_without_native_endpoint(self):
        with patch.dict(os.environ,{'PERSONAL_CONTEXT_ICLOUD_NATIVE_ENABLED':'0'}),patch('subprocess.run') as run:
            with self.assertRaisesRegex(DriveError,'native_tag_verification_required'):Drive().list()
            run.assert_not_called()
    def test_typed_filters_and_transport(self):
        d=Drive()
        with patch.object(d,'_request',return_value={'items':[]}) as request:
            d.search('report',segment='work',tags=['Review'],modified_after='2026-01-01',sort='newest')
            self.assertEqual(request.call_args.args[0]['tags'],['Review'])
            self.assertEqual(request.call_args.args[0]['operation'],'search')
            with self.assertRaises(ValueError):d.write('delete','x')
    def test_smart_uses_only_allowed_candidates_and_preserves_newest(self):
        d=Drive();rows=[{'path':'new.txt','name':'new.txt','modified_at':'2026-01-01T00:00:00Z','revision':'a'*64,'is_dir':False,'tags':[]},
                       {'path':'old.txt','name':'old.txt','modified_at':'2020-01-01T00:00:00Z','revision':'b'*64,'is_dir':False,'tags':[]}]
        class Client:
            def enrich_json(self,**kw):
                self_input=kw['input_data'];assert len(self_input['candidates'])==2
                return {'value':{'matches':[{'id':1,'reason':'older'},{'id':0,'reason':'newer'}]},'model':'fixture'}
        with patch.object(d,'search',return_value={'items':rows,'has_more':False}),patch.object(d,'chunk',return_value={'data_base64':base64.b64encode(b'hello').decode(),'eof':True}),patch('personal_context.enrichment.EnrichmentClient.from_env',return_value=Client()):
            result=d.smart('find relevant documents')
            self.assertEqual([f['path'] for f in result['files']],['new.txt','old.txt'])
            self.assertEqual(result['files'][0]['excerpt'],'hello')
    def test_smart_rejects_forged_ids_and_rechecks_current_access(self):
        d=Drive();row={'path':'a.txt','name':'a.txt','modified_at':'2026-01-01T00:00:00Z','revision':'a'*64,'is_dir':False,'tags':[]}
        class Client:
            def enrich_json(self,**kw):return {'value':{'matches':[{'id':99,'reason':'bad'}]},'model':'fixture'}
        with patch.object(d,'search',return_value={'items':[row],'has_more':False}),patch('personal_context.enrichment.EnrichmentClient.from_env',return_value=Client()):
            with self.assertRaises(DriveError):d.smart('request')
        class Allowed:
            def enrich_json(self,**kw):return {'value':{'matches':[{'id':0,'reason':'match'}]},'model':'fixture'}
        with patch.object(d,'search',return_value={'items':[row],'has_more':False}),patch('personal_context.enrichment.EnrichmentClient.from_env',return_value=Allowed()),patch.object(d,'chunk',side_effect=DriveError('denied')):
            result=d.smart('request');self.assertEqual(result['files'],[])
    def test_writer_uncertainty_no_retry_and_strict_ssh(self):
        import subprocess
        with patch.dict(os.environ,{'PERSONAL_CONTEXT_ICLOUD_NATIVE_ENABLED':'1','PERSONAL_CONTEXT_APPLE_WRITE_TARGET':'user@example.test','PERSONAL_CONTEXT_APPLE_WRITE_REMOTE_COMMAND':'/private/bin/apple-write-receiver'}),patch('personal_context.icloud_gateway.subprocess.run',side_effect=subprocess.TimeoutExpired('ssh',1)) as run:
            with self.assertRaisesRegex(DriveError,'outcome_unconfirmed'):Drive().write('move','a',revision='x',destination='b')
            self.assertEqual(run.call_count,1)
            args=run.call_args.args[0];self.assertIn('StrictHostKeyChecking=yes',args);self.assertNotIn('a',args)
