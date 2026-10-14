import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from personal_context.onboarding import initialize
from personal_context.store import Store
from personal_context.mail_send import _script

class PublicSetupTests(unittest.TestCase):
    def test_demo_is_encrypted_private_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'private'
            result = initialize(root, demo=True)
            key = Path(result['key_file'])
            db = Path(result['database'])
            self.assertEqual(len(key.read_bytes()), 32)
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertNotEqual(db.read_bytes()[:16], b'SQLite format 3\x00')
            store = Store(db, key_file=key)
            try:
                self.assertEqual(len(store.search('fictional', limit=20)), 3)
            finally:
                store.close()
            before = key.read_bytes()
            with self.assertRaises(FileExistsError):
                initialize(root, demo=True)
            self.assertEqual(key.read_bytes(), before)
            config = json.loads((root / 'mcp.json').read_text())
            self.assertEqual(config['mcpServers']['personal-context']['env']['PERSONAL_CONTEXT_DB'], str(db))

    def test_setup_rejects_symlink_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'link'; root.symlink_to(tmp)
            with self.assertRaises(ValueError): initialize(root)

    def test_mail_sender_requires_private_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError): _script({'to': [], 'cc': [], 'bcc': []}, 'Test', 'body')
        with patch.dict(os.environ, {'PERSONAL_CONTEXT_MAIL_FROM': 'sender@example.invalid', 'PERSONAL_CONTEXT_MAIL_ACCOUNT': 'Demo "Account"'}):
            script = _script({'to': ['recipient@example.invalid'], 'cc': [], 'bcc': []}, 'Test', 'body')
            self.assertIn('sender@example.invalid', script)
            self.assertIn('Demo \\"Account\\"', script)
