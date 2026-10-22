import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from personal_context import sync_runner


class SourceOnlySyncTests(unittest.TestCase):
    def run_source_only(self, fast=False, errors=None, flag=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, config_dir = root / 'runtime', root / 'config'
            config_dir.mkdir()
            key = config_dir / 'archive.key'
            key.write_bytes(b'x' * 32)
            key.chmod(0o600)
            (data / 'mac-venv/lib/python3.9/site-packages/typedstream').mkdir(parents=True)
            config = {'calendar_ids': ['fictional-calendar'], 'reminder_ids': [],
                      'remote_host': 'fictional-host', 'remote_project': '/fictional/app',
                      'all_contacts': True, 'all_messages': True, 'all_notes': True,
                      'all_voice_memos': True, 'mailbox_urls': ['fictional://inbox'],
                      'mac_backups_enabled': flag}
            (config_dir / 'config.json').write_text(json.dumps(config))
            commands = []

            def boundary(command, **kwargs):
                commands.append(command)
                if command[0] in ('scp', 'rsync') or any('personal_context.cli backup ' in arg for arg in command):
                    self.fail('Source-only sync attempted an archive backup transfer')
                return '{}'

            with patch.multiple(sync_runner, DATA_DIR=data, CONFIG_DIR=config_dir,
                                KEY_PATH=key, TUNNEL_KEY_PATH=config_dir / 'absent-tunnel.key'), patch(
                    'personal_context.sync_runner.run', side_effect=boundary), patch(
                    'personal_context.sync_runner.mirror_encrypted_blobs',
                    side_effect=AssertionError('Source-only sync attempted a blob backup')):
                if errors is not None:
                    with patch('personal_context.sync_runner.sync_optional_sources', return_value=errors):
                        return sync_runner.main(['--fast'] if fast else [])
                result = sync_runner.main(['--fast'] if fast else [])
            return result, commands

    def test_full_sync_collects_sources_without_archive_or_blob_backups(self):
        result, commands = self.run_source_only()
        self.assertEqual(result, 0)
        for action in ['sync', 'contacts-sync', 'messages-sync', 'notes-sync',
                       'voice-memos-sync', 'mail-sync']:
            self.assertTrue(any(action in command for command in commands), action)

    def test_fast_sync_still_uploads_attachments_and_mail_without_blob_backups(self):
        result, commands = self.run_source_only(fast=True)
        self.assertEqual(result, 0)
        for action in ['fast-sync', 'attachment-sync', 'mail-fast-sync']:
            self.assertTrue(any(action in command for command in commands), action)

    def test_disabled_backups_do_not_hide_failed_sources(self):
        with self.assertRaisesRegex(RuntimeError, 'Notes: fictional failure'):
            self.run_source_only(errors=['Notes: fictional failure'])

    def test_backup_setting_requires_boolean(self):
        with self.assertRaisesRegex(ValueError, 'mac_backups_enabled'):
            self.run_source_only(flag='false')
