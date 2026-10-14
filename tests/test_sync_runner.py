import sys
import unittest
from pathlib import Path

from personal_context.sync_runner import sync_optional_sources, lock_path_for


class SyncRunnerTests(unittest.TestCase):
    def test_fast_and_full_runs_have_independent_locks(self):
        self.assertNotEqual(lock_path_for(Path('/private/data'), True),
                            lock_path_for(Path('/private/data'), False))

    def test_contacts_scope_schedules_complete_contacts_sync(self):
        commands = []
        errors = sync_optional_sources(
            {"all_contacts": True}, Path("/private/config.json"), {},
            lambda command, **kwargs: commands.append(command) or "contacts complete",
        )
        self.assertEqual([], errors)
        self.assertEqual([sys.executable, "-m", "personal_context.cli", "contacts-sync",
                          "--config", "/private/config.json"], commands[0])

    def test_mail_scope_schedules_mail_sync(self):
        commands = []
        errors = sync_optional_sources(
            {"all_mailboxes": True}, Path("/private/config.json"), {},
            lambda command, **kwargs: commands.append(command) or "mail complete",
        )
        self.assertEqual([], errors)
        self.assertEqual([sys.executable, "-m", "personal_context.cli", "mail-sync",
                          "--config", "/private/config.json"], commands[0])

    def test_mail_failure_is_reported_for_backup_followup(self):
        def fail(command, **kwargs):
            raise RuntimeError("mail export failed")
        errors = sync_optional_sources(
            {"mailbox_urls": ["synthetic://inbox"]}, Path("/private/config.json"), {}, fail,
        )
        self.assertEqual(["Mail: mail export failed"], errors)

    @unittest.skipUnless(sys.platform == "darwin", "Mac Messages decoder is required")
    def test_fast_lane_schedules_messages_files(self):
        commands = []
        errors = sync_optional_sources(
            {"all_messages": True}, Path("/private/config.json"),
            {"PYTHONPATH": "/private/src"},
            lambda command, **kwargs: commands.append(command) or "files complete",
            include_attachments=True,
        )
        self.assertEqual([], errors)
        self.assertTrue(any("attachment-sync" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
