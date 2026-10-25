import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from personal_context.refresh_mac_inbox import enqueue, drain

class InboxTests(unittest.TestCase):
    def fixture(self,root):
        path=Path(root)/'config.json';path.write_text('{}');path.chmod(0o600);return path
    def test_source_only_persisted_identity_and_replay(self):
        with tempfile.TemporaryDirectory() as root:
            config=self.fixture(root)
            with patch.dict('os.environ',{'PERSONAL_CONTEXT_DATA_DIR':root}),patch('personal_context.refresh_mac_inbox.kickstart',return_value=True):
                queued=enqueue('calendar','a'*32,'b'*32,config_path=config,wait_seconds=0)
                self.assertTrue(queued['retryable'])
                result={'collection_finished':True,'coverage':'complete','batch_ids':[],'acked_batch_ids':[],'archive_verified':True}
                with patch('personal_context.refresh_worker.run_mac',return_value=result) as collect:
                    self.assertEqual(drain(config_path=config)['processed'],1)
                    self.assertEqual(collect.call_args.args,('calendar','a'*32,'b'*32))
                    self.assertEqual(drain(config_path=config)['processed'],0)
                replay=enqueue('calendar','a'*32,'b'*32,config_path=config,wait_seconds=0)
                self.assertTrue(replay['archive_verified'])
                self.assertEqual(replay['attempt_id'],'b'*32)
    def test_private_config_and_job_identity_required(self):
        with tempfile.TemporaryDirectory() as root:
            config=self.fixture(root);config.chmod(0o644)
            with self.assertRaises(ValueError):enqueue('calendar','a'*32,'b'*32,config_path=config,wait_seconds=0)
            config.chmod(0o600)
            with self.assertRaises(ValueError):enqueue('unknown','a'*32,'b'*32,config_path=config,wait_seconds=0)
    def test_config_changed_and_started_crash_do_not_collect(self):
        with tempfile.TemporaryDirectory() as root:
            config=self.fixture(root)
            with patch.dict('os.environ',{'PERSONAL_CONTEXT_DATA_DIR':root}),patch('personal_context.refresh_mac_inbox.kickstart',return_value=True):
                enqueue('reminder','a'*32,'b'*32,config_path=config,wait_seconds=0)
                config.write_text('{"changed":true}')
                with patch('personal_context.refresh_worker.run_mac') as collect:drain(config_path=config)
                collect.assert_not_called()
                # Restored config returns the exact interrupted/config-changed outcome.
                config.write_text('{}')
                result=enqueue('reminder','a'*32,'b'*32,config_path=config,wait_seconds=0)
                self.assertEqual(result['error_code'],'configuration_changed')
    def test_poll_returns_only_exact_correlated_result(self):
        with tempfile.TemporaryDirectory() as root:
            config=self.fixture(root)
            def kick():drain(config_path=config);return True
            result={'collection_finished':True,'coverage':'complete','batch_ids':[],'acked_batch_ids':[],'archive_verified':True}
            with patch.dict('os.environ',{'PERSONAL_CONTEXT_DATA_DIR':root}),patch('personal_context.refresh_mac_inbox.kickstart',side_effect=kick),patch('personal_context.refresh_worker.run_mac',return_value=result) as collect:
                response=enqueue('reminder','a'*32,'b'*32,config_path=config,wait_seconds=.1)
            self.assertEqual(response['source'],'reminder')
            self.assertEqual(response['refresh_id'],'a'*32)
            self.assertTrue(response['archive_verified'])
            collect.assert_called_once()
    def test_foreign_result_or_reused_attempt_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            config=self.fixture(root)
            with patch.dict('os.environ',{'PERSONAL_CONTEXT_DATA_DIR':root}),patch('personal_context.refresh_mac_inbox.kickstart',return_value=True):
                enqueue('calendar','a'*32,'b'*32,config_path=config,wait_seconds=0)
                with self.assertRaises(ValueError):enqueue('reminder','a'*32,'b'*32,config_path=config,wait_seconds=0)
                job_path=Path(root)/'refresh-inbox'/('b'*32+'.job.json');job=json.loads(job_path.read_text())
                result_path=Path(root)/'refresh-inbox'/('b'*32+'.result.json');result_path.write_text(json.dumps({'job':dict(job,refresh_id='c'*32),'result':{'collection_finished':True}}));result_path.chmod(0o600)
                with self.assertRaises(ValueError):enqueue('calendar','a'*32,'b'*32,config_path=config,wait_seconds=0)
    def test_started_without_result_is_interrupted_and_not_rerun(self):
        with tempfile.TemporaryDirectory() as root:
            config=self.fixture(root)
            with patch.dict('os.environ',{'PERSONAL_CONTEXT_DATA_DIR':root}),patch('personal_context.refresh_mac_inbox.kickstart',return_value=True):
                enqueue('calendar','a'*32,'b'*32,config_path=config,wait_seconds=0)
                job_path=Path(root)/'refresh-inbox'/('b'*32+'.job.json')
                started=job_path.with_name('b'*32+'.started.json');started.write_bytes(job_path.read_bytes());started.chmod(0o600)
                with patch('personal_context.refresh_worker.run_mac') as collect:drain(config_path=config)
                collect.assert_not_called()
                result=enqueue('calendar','a'*32,'b'*32,config_path=config,wait_seconds=0)
                self.assertEqual(result['error_code'],'collector_interrupted')
                self.assertTrue(result['retryable'])
