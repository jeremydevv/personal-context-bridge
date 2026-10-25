import tempfile
import unittest
from personal_context.subscription_auth import PrivateState
from personal_context.refresh_tracking import Coordinator

class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = PrivateState(self.tmp.name, b'x'*32)
        self.c = Coordinator(self.state, {'sources': {'calendar': {'enabled': True, 'capability': 'mac'}}}, clock=lambda:100)
    def tearDown(self): self.tmp.cleanup()
    def test_offline_durable_dedup(self):
        a=self.c.request(['calendar']); b=self.c.request(['calendar'])
        self.assertEqual(a['refresh_id'],b['refresh_id'])
        self.assertEqual(Coordinator(self.state,{},clock=lambda:101).status(a['refresh_id'])['state'],'queued')
    def test_receipt_correlation_and_partial(self):
        r=self.c.request(['calendar']); job=self.c.claim('worker')
        self.c.finish(job, {'batch_ids':['a'], 'acked_batch_ids':[], 'coverage':'complete'})
        self.assertEqual(self.c.status(r['refresh_id'])['state'],'partial')
    def test_expired_lease_retries(self):
        r=self.c.request(['calendar']); self.c.claim('worker')
        self.c.clock=lambda:10000
        job=self.c.claim('new')
        self.assertEqual(job['attempts'],2)
        self.assertNotEqual(job['attempt_id'],self.c.status(r['refresh_id'])['sources']['calendar'].get('previous_attempt_id'))
    def test_empty_acknowledged_snapshot(self):
        r=self.c.request(['calendar']); job=self.c.claim('worker')
        self.c.finish(job,{'batch_ids':[], 'acked_batch_ids':[], 'coverage':'complete','collection_finished':True})
        self.assertEqual(self.c.status(r['refresh_id'])['state'],'complete')
    def test_offline_retries_survive_many_attempts(self):
        r=self.c.request(['calendar'])
        for n in range(6):
            self.c.clock=lambda n=n:100+n*1000
            job=self.c.claim('worker')
            self.assertIsNotNone(job)
            self.c.finish(job,{'retryable':True})
        self.assertEqual(self.c.status(r['refresh_id'])['state'],'waiting')
    def test_schedule_persists_and_deduplicates(self):
        self.c.config['schedules']=[{'name':'fictional','sources':['calendar'],'interval_seconds':900}]
        self.c.schedule(); self.c.schedule()
        with self.c.locked() as data:
            self.assertEqual(len(data['requests']),1)
            self.assertEqual(next(iter(data['requests'].values()))['trigger'],'scheduled')
    def test_stale_worker_cannot_complete_new_attempt(self):
        r=self.c.request(['calendar']);old=self.c.claim('old')
        self.c.clock=lambda:10000
        self.c.claim('new')
        self.assertFalse(self.c.finish(old,{'collection_finished':True,'coverage':'complete','batch_ids':[],'acked_batch_ids':[]}))
        self.assertEqual(self.c.status(r['refresh_id'])['state'],'running')

class ReceiptTests(unittest.TestCase):
    def test_archive_receipt_replay_and_unrelated_batch(self):
        from personal_context.store import Store
        with tempfile.TemporaryDirectory() as root:
            store=Store(root+'/archive.db')
            meta={'refresh_id':'a'*32,'attempt_id':'b'*32,'source':'calendar'}
            batch={'schema':1,'source':'apple-pim','kind':'calendar','scope':'fictional','collected_at':'2026-01-01T00:00:00Z','complete':True,'records':[], 'refresh':dict(meta,batch_id='c'*32)}
            receipt=store.ingest(batch)
            self.assertTrue(receipt['committed'])
            self.assertEqual(store.ingest(batch),receipt)
            changed=dict(batch,collected_at='2026-02-01T00:00:00Z')
            with self.assertRaises(ValueError):store.ingest(changed)
            verified=store.verify_refresh_result(meta,{'batch_ids':['c'*32],'collection_finished':True,'coverage':'complete'})
            self.assertEqual(verified['acked_batch_ids'],['c'*32])
            with self.assertRaises(ValueError):store.verify_refresh_result(dict(meta,attempt_id='d'*32),{'batch_ids':['c'*32]})
            store.close()
    def test_spool_retains_batch_until_exact_ack(self):
        import json
        from personal_context.spool import Spool
        with tempfile.TemporaryDirectory() as root:
            spool=Spool(root);Spool.begin_tracking('a'*32,'b'*32,'calendar')
            try:
                spool.enqueue([{'schema':1,'records':[]}])
                with self.assertRaises(RuntimeError):spool.flush(lambda data:{'receipts':[]})
                self.assertEqual(len(spool.pending()),1)
                def deliver(data):
                    return {'receipts':[dict(json.loads(data)['refresh'],committed=True)]}
                self.assertEqual(spool.flush(deliver),1)
                self.assertEqual(Spool.produced,Spool.acknowledged)
            finally:Spool.tracking=None
    def test_source_filter_disables_unrelated_native_collectors(self):
        from personal_context.refresh_worker import source_config
        config={'calendar_ids':['fictional'],'reminder_ids':['other'],'all_contacts':True,'all_messages':True,'all_notes':True,'all_reminders':True,'all_calendars':True,'all_mailboxes':True,'mailbox_urls':['fictional:mail']}
        selected=source_config(config,'calendar')
        self.assertTrue(selected['all_calendars'])
        self.assertFalse(selected['all_reminders'])
        self.assertFalse(selected['all_contacts'])
        self.assertEqual(selected['reminder_ids'],[])
        self.assertEqual(selected['mailbox_urls'],[])
    def test_source_envelope_cannot_claim_other_kind(self):
        from personal_context.store import Store
        with tempfile.TemporaryDirectory() as root:
            store=Store(root+'/archive.db')
            batch={'schema':1,'source':'apple-pim','kind':'reminder','scope':'fictional','collected_at':'2026-01-01T00:00:00Z','complete':True,'records':[], 'refresh':{'refresh_id':'a'*32,'attempt_id':'b'*32,'batch_id':'c'*32,'source':'calendar'}}
            with self.assertRaises(ValueError):store.ingest(batch)
            store.close()

class WorkerTests(unittest.TestCase):
    def test_local_zero_exit_without_owned_receipt_is_partial(self):
        from unittest.mock import patch
        from personal_context.refresh_worker import dispatch
        config={'sources':{'obsidian':{'capability':'local_command','command':['/bin/true']}}}
        job={'refresh_id':'a'*32,'attempt_id':'b'*32,'source':'obsidian','mode':'recent'}
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ',{'PERSONAL_CONTEXT_REFRESH_DIR':root}):
            result=dispatch(job,config)
        self.assertFalse(result['collection_finished'])
        self.assertEqual(result['error_code'],'pipeline_exited_without_receipt')
    def test_local_owned_receipt_preserves_pipeline_phase(self):
        from unittest.mock import patch
        from personal_context.refresh_worker import dispatch
        import json
        job={'refresh_id':'a'*32,'attempt_id':'b'*32,'source':'obsidian','mode':'recent'}
        config={'sources':{'obsidian':{'capability':'local_command','command':['/bin/true']}}}
        receipt=dict(job,collection_finished=True,coverage='complete',batch_ids=[],acked_batch_ids=[])
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ',{'PERSONAL_CONTEXT_REFRESH_DIR':root}),patch('personal_context.refresh_worker.bounded_run',return_value=json.dumps(receipt)):
            result=dispatch(job,config)
        self.assertEqual(result['completion_kind'],'local_pipeline')
        self.assertEqual(result['attempt_id'],job['attempt_id'])
    def test_mac_ssh_remote_command_only_uses_trusted_config(self):
        from unittest.mock import patch
        from personal_context.refresh_worker import dispatch
        import json
        job={'refresh_id':'a'*32,'attempt_id':'b'*32,'source':'calendar','mode':'recent'}
        config={'mac_target':'fixture@mac.invalid','mac_python':'/private/runtime/python','mac_config':'/private/config.json','mac_env':{'PYTHONPATH':'/private/runtime/src'},'sources':{'calendar':{'capability':'mac'}}}
        result=dict(job,collection_finished=True,coverage='complete',batch_ids=[],acked_batch_ids=[])
        with patch('personal_context.refresh_worker.bounded_run',return_value=json.dumps(result)) as run:
            dispatch(job,config)
        command=run.call_args.args[0]
        self.assertIn('--source calendar',command[-1])
        self.assertIn('PYTHONPATH=/private/runtime/src',command[-1])
        self.assertNotIn('sync_runner',command[-1])
    def test_receipt_failure_rolls_back_archive_records(self):
        from personal_context.store import Store
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            store=Store(root+'/archive.db')
            batch={'schema':1,'source':'apple-pim','kind':'calendar','scope':'fictional','collected_at':'2026-01-01T00:00:00Z','complete':True,'records':[{'id':'fixture','title':'Fictional event'}], 'refresh':{'refresh_id':'a'*32,'attempt_id':'b'*32,'batch_id':'c'*32,'source':'calendar'}}
            with patch.object(store,'_write_refresh_receipt',side_effect=RuntimeError('injected_receipt_failure')):
                with self.assertRaises(RuntimeError):store.ingest(batch)
            self.assertIsNone(store.get('calendar','fixture'))
            self.assertIsNone(store.last_sync('calendar'))
            self.assertEqual(store.db.execute('SELECT count(*) FROM refresh_receipts').fetchone()[0],0)
            store.close()

class ReplayRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.c=Coordinator(PrivateState(self.tmp.name,b'x'*32),{'sources':{'calendar':{'enabled':True,'capability':'mac'},'icloud_drive':{'enabled':True,'capability':'requires_auth'}}},clock=lambda:100)
    def tearDown(self):self.tmp.cleanup()
    def test_explicit_join_identity_survives_completion_and_replay(self):
        original=self.c.request(['calendar'])
        joined=self.c.request(['calendar'],request_id='b'*32)
        self.assertEqual(joined['refresh_id'],'b'*32)
        job=self.c.claim('fixture')
        self.c.finish(job,{'collection_finished':True,'coverage':'complete','batch_ids':[],'acked_batch_ids':[]})
        replay=self.c.request(['calendar'],request_id='b'*32)
        self.assertEqual(replay['state'],'complete')
        self.assertIsNone(self.c.claim('no-duplicate'))
    def test_mixed_terminal_and_waiting_request_deduplicates(self):
        first=self.c.request(['calendar','icloud_drive'])
        job=self.c.claim('fixture');self.c.finish(job,{'retryable':True})
        second=self.c.request(['calendar','icloud_drive'])
        self.assertEqual(first['refresh_id'],second['refresh_id'])
    def test_overlapping_requests_share_active_source(self):
        self.c.request(['calendar'])
        self.c.request(['calendar','icloud_drive'],request_id='c'*32)
        first=self.c.claim('fixture')
        self.assertIsNotNone(first)
        self.assertIsNone(self.c.claim('no-duplicate'))

class LocalEnvironmentTests(unittest.TestCase):
    def test_private_source_environment_preserves_inherited_and_fixed_identity(self):
        from unittest.mock import patch
        from personal_context.refresh_worker import dispatch
        job={'refresh_id':'a'*32,'attempt_id':'b'*32,'source':'obsidian','mode':'recent'}
        config={'sources':{'obsidian':{'capability':'local_command','command':['/bin/true'],'env':{'OBSIDIAN_SYNC_CONFIG':'/private/fictional-config.json','PERSONAL_CONTEXT_REFRESH_ID':'override'}}}}
        with tempfile.TemporaryDirectory() as root,patch.dict('os.environ',{'PERSONAL_CONTEXT_REFRESH_DIR':root,'FICTIONAL_INHERITED':'retained'}),patch('personal_context.refresh_worker.bounded_run',return_value='') as runner:
            dispatch(job,config)
        env=runner.call_args.kwargs['env']
        self.assertEqual(env['OBSIDIAN_SYNC_CONFIG'],'/private/fictional-config.json')
        self.assertEqual(env['FICTIONAL_INHERITED'],'retained')
        self.assertEqual(env['PERSONAL_CONTEXT_REFRESH_ID'],job['refresh_id'])
    def test_push_only_waiter_does_not_block_later_native_collection(self):
        with tempfile.TemporaryDirectory() as root:
            c=Coordinator(PrivateState(root,b'x'*32),{'sources':{'calendar':{'enabled':True,'capability':'mac'},'health':{'enabled':True,'capability':'waiting_for_device'}}},clock=lambda:100)
            original=c.request(['calendar','health']);job=c.claim('fixture')
            c.finish(job,{'collection_finished':True,'coverage':'complete','batch_ids':[],'acked_batch_ids':[]})
            c.clock=lambda:100000
            later=c.request(['calendar','health'])
            self.assertNotEqual(later['refresh_id'],original['refresh_id'])
            self.assertEqual(c.claim('new')['source'],'calendar')

class MessageCadenceTests(unittest.TestCase):
    def test_recent_messages_preserves_bounded_attachment_pass(self):
        from unittest.mock import patch
        from personal_context.refresh_worker import run_mac
        calls=[]
        with tempfile.TemporaryDirectory() as root:
            config=__import__('pathlib').Path(root)/'config.json';config.write_text('{}');config.chmod(0o600)
            def collect(argv):calls.append(argv);return 0
            def deliver(config,payload):
                import json
                return {'refresh_result':dict(json.loads(payload)['refresh_result'],archive_verified=True)}
            with patch.dict('os.environ',{'PERSONAL_CONTEXT_DATA_DIR':root}),patch('personal_context.cli.load_config',return_value={'all_messages':True,'calendar_ids':[],'reminder_ids':[]}),patch('personal_context.cli.main',side_effect=collect),patch('personal_context.cli.deliver_ssh',side_effect=deliver):
                result=run_mac('message','a'*32,'b'*32,config_path=config)
        self.assertEqual([c[0] for c in calls],['messages-sync','attachment-sync'])
        self.assertIn('50',calls[1])
        self.assertTrue(result['attachment_processing']['invoked'])
    def test_collection_lane_matches_mode_and_restores_callers_environment(self):
        from unittest.mock import patch
        from personal_context.refresh_worker import run_mac
        import os,json
        seen=[]
        with tempfile.TemporaryDirectory() as root:
            config=__import__('pathlib').Path(root)/'config.json';config.write_text('{}');config.chmod(0o600)
            def collect(argv):seen.append(os.environ.get('PERSONAL_CONTEXT_SYNC_LANE'));return 0
            def deliver(config,payload):return {'refresh_result':dict(json.loads(payload)['refresh_result'],archive_verified=True)}
            with patch.dict('os.environ',{'PERSONAL_CONTEXT_DATA_DIR':root,'PERSONAL_CONTEXT_SYNC_LANE':'original'}),patch('personal_context.cli.load_config',return_value={'all_messages':True,'calendar_ids':[],'reminder_ids':[]}),patch('personal_context.cli.main',side_effect=collect),patch('personal_context.cli.deliver_ssh',side_effect=deliver):
                run_mac('message','a'*32,'b'*32,mode='recent',config_path=config)
                self.assertEqual(os.environ['PERSONAL_CONTEXT_SYNC_LANE'],'original')
                run_mac('message','c'*32,'d'*32,mode='full',config_path=config)
                self.assertEqual(os.environ['PERSONAL_CONTEXT_SYNC_LANE'],'original')
        self.assertEqual(seen,['fast','fast','full','full'])

class SourceRuntimeTests(unittest.TestCase):
    def test_canvas_uses_trusted_source_runtime_override(self):
        from unittest.mock import patch
        from personal_context.refresh_worker import dispatch
        import json
        job={'refresh_id':'a'*32,'attempt_id':'b'*32,'source':'canvas','mode':'recent'}
        config={'mac_target':'fixture@mac.invalid','mac_python':'/private/default/python','mac_config':'/private/config.json','sources':{'canvas':{'capability':'mac','mac_python':'/private/canvas/python'}}}
        with patch('personal_context.refresh_worker.bounded_run',return_value=json.dumps(job)) as run:
            dispatch(job,config)
        command=run.call_args.args[0][-1]
        self.assertIn('/private/canvas/python',command)
        self.assertNotIn('/private/default/python',command)
    def test_relative_source_runtime_override_is_rejected(self):
        from personal_context.refresh_worker import dispatch
        job={'refresh_id':'a'*32,'attempt_id':'b'*32,'source':'canvas','mode':'recent'}
        config={'mac_target':'fixture@mac.invalid','mac_python':'/private/default/python','mac_config':'/private/config.json','sources':{'canvas':{'capability':'mac','mac_python':'relative-python'}}}
        with self.assertRaises(ValueError):dispatch(job,config)

class CanvasSpoolCoverageTests(unittest.TestCase):
    def test_nested_unavailable_canvas_coverage_overrides_outer_success(self):
        from personal_context.spool import Spool
        import json
        with tempfile.TemporaryDirectory() as root:
            spool=Spool(root);Spool.begin_tracking('a'*32,'b'*32,'canvas')
            try:
                batch={'schema':1,'source':'canvas-lms','kind':'canvas_collection_state','scope':'fictional','complete':True,'collected_at':'2026-01-01T00:00:00Z','records':[{'id':'fixture','title':'Coverage','payload':{'features':{'module':{'status':'unavailable'}}}}]}
                spool.enqueue([batch])
                spool.flush(lambda payload:{'receipts':[dict(json.loads(payload)['refresh'],committed=True)]})
                self.assertEqual(Spool.tracking_result()['coverage'],'partial')
                self.assertEqual(Spool.produced,Spool.acknowledged)
            finally:Spool.tracking=None
    def test_coverage_flag_resets_each_invocation_and_ignores_other_sources(self):
        from personal_context.spool import Spool
        with tempfile.TemporaryDirectory() as root:
            spool=Spool(root)
            Spool.begin_tracking('a'*32,'b'*32,'calendar')
            try:
                spool.enqueue([{'schema':1,'source':'apple-pim','kind':'calendar','records':[{'payload':{'status':'unavailable'}}]}])
                self.assertEqual(Spool.tracking_result()['coverage'],'complete')
                Spool.begin_tracking('c'*32,'d'*32,'canvas')
                self.assertEqual(Spool.tracking_result()['coverage'],'complete')
            finally:Spool.tracking=None
    def test_private_runner_outer_success_cannot_complete_partial_payload(self):
        from unittest.mock import patch
        from personal_context.refresh_worker import run_mac
        from personal_context.spool import Spool
        import json,os
        with tempfile.TemporaryDirectory() as root:
            config=__import__('pathlib').Path(root)/'config.json';config.write_text('{}');config.chmod(0o600)
            def runner(**kwargs):
                spool=Spool(root+'/canvas')
                spool.enqueue([{'schema':1,'source':'canvas-lms','kind':'canvas_course','scope':'fictional','records':[{'id':'fixture','payload':{'module_collection':{'status':'unavailable'}}}]}])
                spool.flush(lambda data:{'receipts':[dict(json.loads(data)['refresh'],committed=True)]})
                return {'accounts':{'fictional':{}},'pending':0}
            def deliver(config,payload):return {'refresh_result':dict(json.loads(payload)['refresh_result'],archive_verified=True)}
            with patch.dict(os.environ,{'PERSONAL_CONTEXT_DATA_DIR':root}),patch('personal_context.cli.load_config',return_value={'calendar_ids':[],'reminder_ids':[]}),patch('personal_context.canvas_sync_runner.run',side_effect=runner),patch('personal_context.cli.deliver_ssh',side_effect=deliver):
                result=run_mac('canvas','a'*32,'b'*32,config_path=config)
            self.assertEqual(result['coverage'],'partial')
            self.assertTrue(result['archive_verified'])
