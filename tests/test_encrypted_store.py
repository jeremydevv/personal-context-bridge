import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from personal_context.store import Store
from personal_context.service import QueryService
from unittest.mock import patch

try:
    from sqlcipher3 import dbapi2 as sqlcipher
except ImportError:
    sqlcipher = None


@unittest.skipIf(sqlcipher is None, "SQLCipher is not installed")
class EncryptedStoreTests(unittest.TestCase):
    def test_encrypted_query_service_opens_archive_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archive.sqlite3"
            key_path = Path(directory) / "key"
            key_path.write_bytes(os.urandom(32))
            key_path.chmod(0o600)
            store = Store(path, key_file=key_path)
            store.ingest({"schema": 1, "source": "apple-pim", "kind": "calendar",
                          "scope": "calendar:test", "collected_at": "2026-10-01T00:00:00Z",
                          "complete": True, "records": [{"id": "one", "title": "Kept"}]})
            store.close()
            with patch.dict(os.environ, {"PERSONAL_CONTEXT_KEY_FILE": str(key_path)}):
                service = QueryService(path)
                self.assertEqual("Kept", service.get("calendar", "one")["record"]["title"])
                with self.assertRaises(sqlcipher.OperationalError):
                    service._use(lambda reader: reader.db.execute("DELETE FROM records"))
                self.assertEqual("Kept", service.get("calendar", "one")["record"]["title"])

    def test_archive_is_encrypted_and_reopens_with_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archive.sqlite3"
            key_path = Path(directory) / "key"
            key_path.write_bytes(os.urandom(32))
            key_path.chmod(0o600)
            store = Store(path, key_file=key_path)
            store.ingest({"schema": 1, "source": "apple-pim", "kind": "calendar",
                          "scope": "calendar:test", "collected_at": "2026-09-30T20:00:00Z",
                          "complete": True, "records": [{"id": "one", "title": "Private event"}]})
            store.close()
            self.assertNotEqual(b"SQLite format 3\x00", path.read_bytes()[:16])
            with sqlite3.connect(str(path)) as plain:
                with self.assertRaises(sqlite3.DatabaseError):
                    plain.execute("SELECT title FROM records").fetchall()
            reopened = Store(path, key_file=key_path)
            self.assertEqual("Private event", reopened.get("calendar", "one")["title"])
            reopened.close()

    def test_wrong_key_cannot_open_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archive.sqlite3"
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            first.write_bytes(os.urandom(32))
            second.write_bytes(os.urandom(32))
            first.chmod(0o600)
            second.chmod(0o600)
            Store(path, key_file=first).close()
            with self.assertRaises(sqlcipher.DatabaseError):
                Store(path, key_file=second)


if __name__ == "__main__":
    unittest.main()
