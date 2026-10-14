"""Confirm the Health archive is encrypted and can be reopened with its key."""

import os
import tempfile
import unittest

from sqlcipher3 import dbapi2 as cipher


class CipherStoreTest(unittest.TestCase):
    def test_encrypted_file_requires_correct_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "health.sqlite3")
            key = bytes(range(32))
            db = cipher.connect(path)
            db.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
            self.assertTrue(db.execute("PRAGMA cipher_version").fetchone())
            db.execute("CREATE TABLE proof (value INTEGER)")
            db.execute("INSERT INTO proof VALUES (7)")
            db.commit()
            db.close()

            with open(path, "rb") as archive:
                self.assertNotEqual(archive.read(16), b"SQLite format 3\x00")

            db = cipher.connect(path)
            db.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
            self.assertEqual(db.execute("SELECT value FROM proof").fetchone()[0], 7)
            db.close()

            db = cipher.connect(path)
            db.execute("PRAGMA key = \"x'" + bytes(reversed(key)).hex() + "'\"")
            with self.assertRaises(cipher.DatabaseError):
                db.execute("SELECT value FROM proof").fetchone()
            db.close()


if __name__ == "__main__":
    unittest.main()
