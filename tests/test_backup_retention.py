import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

from personal_context.sync_runner import prune_backups


class BackupRetentionTests(unittest.TestCase):
    DiskUsage = namedtuple("DiskUsage", "total used free")

    def test_prunes_oldest_for_incoming_copy_but_preserves_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("a", "b", "c"):
                (root / (name + ".sqlite3")).write_bytes(b"x" * 10)
            with patch("personal_context.sync_runner.shutil.disk_usage", return_value=self.DiskUsage(100, 0, 100)):
                prune_backups(root, incoming_bytes=10, max_copies=3,
                              max_total_bytes=25, min_free_bytes=8)
            self.assertEqual(["c.sqlite3"], [p.name for p in root.glob("*.sqlite3")])

    def test_refuses_transfer_when_last_copy_must_be_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "only.sqlite3").write_bytes(b"x" * 10)
            with patch("personal_context.sync_runner.shutil.disk_usage", return_value=self.DiskUsage(100, 95, 5)):
                with self.assertRaisesRegex(RuntimeError, "not enough Mac free space"):
                    prune_backups(root, incoming_bytes=10, min_free_bytes=8)
            self.assertTrue((root / "only.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
