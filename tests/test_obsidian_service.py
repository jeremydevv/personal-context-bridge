import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from personal_context.obsidian_service import ObsidianVaultService


class ObsidianServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "Notes").mkdir()
        (self.root / "Projects").mkdir()
        (self.root / "Journal").mkdir()
        (self.root / "Notes" / "Plan.md").write_text("# Plan\nOld step\n")
        self.service = ObsidianVaultService(self.root, write_enabled=True, require_mount=False)

    def test_revision_guard_and_private_backup(self):
        before = self.service.read_note("Notes", "Plan.md")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.service.write_note("Notes", "Plan.md", "overwrite", "")
        result = self.service.replace_in_note(
            "Notes", "Plan.md", "Old step", "New step", before["sha256"])
        self.assertEqual(result["replacements"], 1)
        self.assertEqual(self.service.read_note("Notes", "Plan.md")["content"],
                         "# Plan\nNew step\n")
        backups = list((self.root / ".mcp-backups" / "Notes").glob("*.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), before["content"])
        with self.assertRaisesRegex(ValueError, "changed"):
            self.service.append_note("Notes", "Plan.md", "again", before["sha256"])

    def test_create_then_soft_delete_requires_exact_revision(self):
        created = self.service.write_note("Projects", "New/Note.md", "hello")
        self.assertTrue(created["created"])
        self.assertEqual(created["sha256"], hashlib.sha256(b"hello").hexdigest())
        with self.assertRaisesRegex(ValueError, "changed"):
            self.service.trash_note("Projects", "New/Note.md", "0" * 64)
        removed = self.service.trash_note("Projects", "New/Note.md", created["sha256"])
        self.assertTrue(removed["trashed"])
        self.assertFalse((self.root / "Projects" / "New" / "Note.md").exists())
        self.assertEqual(len(list((self.root / ".mcp-backups" / "Projects").glob("*.md"))), 1)

    def test_traversal_symlink_and_hidden_writes_rejected(self):
        (self.root / "Notes" / "link.md").symlink_to(self.root / "Projects" / "out.md")
        for path in ("../Projects/out.md", "/tmp/out.md", "folder/../out.md", "link.md"):
            with self.subTest(path=path), self.assertRaises((ValueError, FileNotFoundError)):
                self.service.write_note("Notes", path, "bad")
        with self.assertRaises(ValueError):
            self.service.write_note("Notes", ".obsidian/app.json", "bad")
        with self.assertRaises(ValueError):
            self.service.read_note("Notes", "link.md")
        with self.assertRaises(ValueError):
            self.service.read_note("Unknown", "Plan.md")

    def test_write_gate_and_mount_gate(self):
        readonly = ObsidianVaultService(self.root, write_enabled=False, require_mount=False)
        with self.assertRaises(PermissionError):
            readonly.write_note("Notes", "New.md", "no")
        with self.assertRaisesRegex(RuntimeError, "not mounted"):
            ObsidianVaultService(self.root, require_mount=True)

    def test_search_and_binary_chunk_are_bounded(self):
        (self.root / "Journal" / "image.bin").write_bytes(b"0123456789")
        result = self.service.search_notes("old step")
        self.assertEqual([(r["vault"], r["path"]) for r in result["results"]],
                         [("Notes", "Plan.md")])
        chunk = self.service.read_attachment_chunk("Journal", "image.bin", 3, 4)
        self.assertEqual(chunk["next_offset"], 7)
        self.assertFalse(chunk["eof"])

    def test_sync_status_reports_stale_after_thirty_minutes(self):
        status_dir = self.root / ".mcp-backups"
        status_dir.mkdir()
        old = datetime.now(timezone.utc) - timedelta(minutes=31)
        (status_dir / "sync_status.json").write_text(json.dumps({
            "last_success_at": old.isoformat(), "mode": "--run"}))
        status = self.service.sync_status()
        self.assertIn("stale", status)
        self.assertTrue(status["stale"])
        self.assertGreaterEqual(status["age_seconds"], 30 * 60)

    def test_sync_status_reports_fresh_recent_run(self):
        status_dir = self.root / ".mcp-backups"
        status_dir.mkdir()
        recent = datetime.now(timezone.utc) - timedelta(minutes=1)
        (status_dir / "sync_status.json").write_text(json.dumps({
            "last_success_at": recent.isoformat(), "mode": "--run"}))
        status = self.service.sync_status()
        self.assertIn("stale", status)
        self.assertFalse(status["stale"])
        self.assertLess(status["age_seconds"], 30 * 60)


if __name__ == "__main__":
    unittest.main()
