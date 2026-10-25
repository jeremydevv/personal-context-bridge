import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from personal_context.canvas_sync_runner import load_accounts, run

class CanvasRunnerTests(unittest.TestCase):
    def fixture(self,root):
        root=Path(root);config=root/'config';config.mkdir();data=root/'data'
        token=config/'token';token.write_text('fictional-token');token.chmod(0o600)
        accounts=config/'canvas-accounts.json';accounts.write_text(json.dumps({'accounts':[{'label':'fictional','base_url':'https://canvas.invalid','token_file':str(token)}]}));accounts.chmod(0o600)
        transfer=config/'config.json';transfer.write_text(json.dumps({'remote_host':'archive.invalid','remote_project':'/private/runtime'}));transfer.chmod(0o600)
        return config,data
    def test_requires_private_accounts(self):
        with tempfile.TemporaryDirectory() as root:
            config,_=self.fixture(root);(config/'canvas-accounts.json').chmod(0o644)
            with self.assertRaises(ValueError):load_accounts(config/'canvas-accounts.json')
    def test_partial_canvas_coverage_and_acknowledgements(self):
        batch={'schema':1,'source':'canvas-lms','kind':'canvas_collection_state','scope':'fictional','complete':True,'collected_at':'2026-01-01T00:00:00Z','records':[{'id':'fictional','title':'Coverage','payload':{'features':{'page':{'status':'unavailable'}}}}]}
        with tempfile.TemporaryDirectory() as root:
            config,data=self.fixture(root)
            with patch('personal_context.canvas_sync_runner.CanvasClient') as client,patch('personal_context.canvas_sync_runner.collect_batches',return_value=[batch]),patch('personal_context.canvas_sync_runner.deliver_ssh',return_value={'receipts':[]}):
                result=run(config,data)
        self.assertEqual(result['coverage'],'partial')
        self.assertEqual(result['pending'],0)
        client.return_value.close.assert_called_once()
    def test_successful_empty_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            config,data=self.fixture(root)
            with patch('personal_context.canvas_sync_runner.CanvasClient'),patch('personal_context.canvas_sync_runner.collect_batches',return_value=[]):result=run(config,data)
        self.assertEqual(result['coverage'],'complete')
        self.assertEqual(result['accounts'],1)
