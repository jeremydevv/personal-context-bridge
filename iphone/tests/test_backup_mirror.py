"""Reject forged remote backup paths and preserve prior Mac ciphertext copies."""

import sys
import tempfile
import unittest
from pathlib import Path

from iphone_context.backup_mirror import checked_remote_path, prune_local_copies


class BackupMirrorTest(unittest.TestCase):
    def test_remote_path_is_scoped_to_expected_source_and_filename(self):
        good = "data/backups/health/backup-123456789-abcdef0123456789abcdef0123456789.sqlite3"
        self.assertEqual(checked_remote_path("health", good), good)
        for bad in ("../secret", "/etc/passwd", "data/backups/travel/backup-123.sqlite3",
                    "data/backups/health/../../secret.sqlite3"):
            with self.assertRaises(ValueError):
                checked_remote_path("health", bad)

    def test_retention_keeps_at_least_previous_verified_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("a", "b", "c"):
                (root / (name + ".sqlite3")).write_bytes(b"x")
            prune_local_copies(root, retain=2)
            self.assertEqual(["b.sqlite3", "c.sqlite3"],
                             sorted(path.name for path in root.glob("*.sqlite3")))

    def test_size_cap_does_not_delete_the_only_previous_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "previous.sqlite3"
            previous.write_bytes(b"x" * 10)
            with self.assertRaises(RuntimeError):
                prune_local_copies(root, incoming_bytes=10, max_total_bytes=15,
                                   min_free_bytes=0)
            self.assertEqual(previous.read_bytes(), b"x" * 10)


if __name__ == "__main__":
    unittest.main()
