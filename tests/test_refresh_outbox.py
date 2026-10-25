import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from personal_context.refresh_worker import enqueue_scheduled

class OutboxTests(unittest.TestCase):
    def fixture(self,root):
        config=Path(root)/'config.json';config.write_text('{}');config.chmod(0o600)
        outbox=Path(root)/'refresh-outbox';outbox.mkdir()
        return config,outbox
    def test_wrong_id_ack_does_not_remove_pending_intent(self):
        with tempfile.TemporaryDirectory() as root:
            config,outbox=self.fixture(root)
            with patch.dict('os.environ',{'PERSONAL_CONTEXT_DATA_DIR':root}),patch('personal_context.cli.load_config',return_value={'remote_host':'archive.invalid','remote_project':'/private/runtime'}),patch('personal_context.refresh_worker.bounded_run',return_value=json.dumps({'requested':True,'refresh_id':'f'*32})):
                result=enqueue_scheduled('canvas',config_path=config)
            self.assertEqual(result['local_pending'],1)
    def test_corrupt_entry_retained_for_recovery_without_blocking_valid_intent(self):
        with tempfile.TemporaryDirectory() as root:
            config,outbox=self.fixture(root);(outbox/('a'*32+'.json')).write_text('{')
            with patch.dict('os.environ',{'PERSONAL_CONTEXT_DATA_DIR':root}),patch('personal_context.cli.load_config',return_value={'remote_host':'archive.invalid','remote_project':'/private/runtime'}),patch('personal_context.refresh_worker.bounded_run',side_effect=OSError):
                result=enqueue_scheduled('canvas',config_path=config)
            self.assertEqual(result['local_pending'],1)
            self.assertEqual(result['corrupt_pending'],1)
            self.assertEqual(len(list(outbox.glob('*.corrupt'))),1)
    def test_interruption_before_atomic_publish_leaves_no_partial_json(self):
        with tempfile.TemporaryDirectory() as root:
            config,outbox=self.fixture(root)
            with patch.dict('os.environ',{'PERSONAL_CONTEXT_DATA_DIR':root}),patch('personal_context.cli.load_config',return_value={'remote_host':'archive.invalid','remote_project':'/private/runtime'}),patch('personal_context.refresh_worker.os.replace',side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):enqueue_scheduled('canvas',config_path=config)
            self.assertEqual(list(outbox.glob('*.json')),[])
