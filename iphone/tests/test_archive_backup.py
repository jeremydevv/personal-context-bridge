"""A live SQLCipher archive can be backed up without writing plaintext."""

import sys
import tempfile
import unittest
from pathlib import Path

from sqlcipher3 import dbapi2 as cipher

from iphone_context.archive_backup import snapshot_archive


class ArchiveBackupTest(unittest.TestCase):
    def test_encrypted_snapshot_reopens_and_rotates_only_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, key_file, backups = root / "live.sqlite3", root / "key", root / "backups"
            key = bytes(range(32))
            key_file.write_bytes(key)
            key_file.chmod(0o600)
            db = cipher.connect(str(source))
            db.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
            db.execute("CREATE TABLE proof (value INTEGER)")
            db.execute("INSERT INTO proof VALUES (7)")
            db.commit()
            db.close()

            first = snapshot_archive(source, key_file, backups, retain=2)
            path = Path(first["path"])
            self.assertEqual(first["bytes"], path.stat().st_size)
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")
            reopened = cipher.connect(str(path))
            reopened.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
            self.assertEqual(reopened.execute("SELECT value FROM proof").fetchone()[0], 7)
            reopened.close()

            snapshot_archive(source, key_file, backups, retain=2)
            snapshot_archive(source, key_file, backups, retain=2)
            self.assertEqual(len(list(backups.glob("*.sqlite3"))), 2)

    def test_bad_key_keeps_existing_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, key_file, backups = root / "live.sqlite3", root / "key", root / "backups"
            good_key = bytes(range(32))
            key_file.write_bytes(good_key)
            key_file.chmod(0o600)
            db = cipher.connect(str(source))
            db.execute("PRAGMA key = \"x'" + good_key.hex() + "'\"")
            db.execute("CREATE TABLE proof (value INTEGER)")
            db.close()
            existing = backups / "previous.sqlite3"
            backups.mkdir()
            existing.write_bytes(b"keep me")
            key_file.write_bytes(bytes(reversed(good_key)))

            with self.assertRaises(cipher.DatabaseError):
                snapshot_archive(source, key_file, backups)
            self.assertEqual(existing.read_bytes(), b"keep me")
            self.assertFalse(list(backups.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
