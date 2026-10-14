import sqlite3
import tempfile
import unittest
from pathlib import Path

from personal_context.messages_collect import collect_messages, PARTITIONS
from personal_context.store import Store


class MessagesCollectorTests(unittest.TestCase):
    def fixture(self, path):
        connection = sqlite3.connect(path)
        connection.executescript("""
            CREATE TABLE message (
                ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, attributedBody BLOB,
                subject TEXT, date INTEGER, handle_id INTEGER, is_from_me INTEGER,
                service TEXT, is_sent INTEGER, is_read INTEGER, is_system_message INTEGER,
                is_spam INTEGER, date_edited INTEGER, date_retracted INTEGER,
                associated_message_guid TEXT, associated_message_type INTEGER,
                reply_to_guid TEXT
            );
            CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
            CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, guid TEXT, display_name TEXT,
                               chat_identifier TEXT);
            CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
            CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
            CREATE TABLE attachment (ROWID INTEGER PRIMARY KEY, guid TEXT,
                                     transfer_name TEXT, mime_type TEXT, total_bytes INTEGER);
            CREATE TABLE message_attachment_join (message_id INTEGER, attachment_id INTEGER);
            INSERT INTO handle VALUES (1,'person@example.test');
            INSERT INTO chat VALUES (1,'chat-1','Friends','person@example.test');
            INSERT INTO chat_handle_join VALUES (1,1);
            INSERT INTO attachment VALUES (1,'attachment-1','picture.jpg','image/jpeg',123);
            INSERT INTO message VALUES (1,'message-1','hello synthetic',NULL,NULL,
                781022516948000000,1,0,'iMessage',1,1,0,0,0,0,NULL,NULL,NULL);
            INSERT INTO message VALUES (2,'message-2',NULL,NULL,NULL,
                781022516949000000,1,0,'iMessage',1,1,0,0,0,0,NULL,NULL,NULL);
            INSERT INTO chat_message_join VALUES (1,1);
            INSERT INTO chat_message_join VALUES (1,2);
            INSERT INTO message_attachment_join VALUES (2,1);
        """)
        connection.commit()
        return connection

    def test_complete_snapshot_and_tombstone(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat.db"
            source = self.fixture(path)
            store = Store(Path(directory) / "archive.sqlite3")
            try:
                batches, counts = collect_messages(path, "2026-10-01T00:00:00Z")
                self.assertEqual(PARTITIONS, len(batches))
                self.assertEqual({"messages": 2, "missing_bodies": 1, "attachments": 1}, counts)
                self.assertTrue(all(batch["complete"] for batch in batches))
                for batch in batches:
                    store.ingest(batch)
                self.assertIn("hello synthetic", store.get("message", "message-1")["body"])
                self.assertEqual("picture.jpg", store.get("message", "message-2")["payload"]["attachments"][0]["name"])

                source.execute("DELETE FROM message WHERE ROWID=2")
                source.commit()
                updated, _ = collect_messages(path, "2026-10-02T00:00:00Z")
                for batch in updated:
                    store.ingest(batch)
                self.assertIsNone(store.get("message", "message-2"))
                self.assertEqual(2, store.version_count("message", "message-2"))
            finally:
                store.close()
                source.close()

    def test_truncated_source_cannot_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat.db"
            source = self.fixture(path)
            try:
                with self.assertRaisesRegex(ValueError, "configured limit"):
                    collect_messages(path, limit=2)
            finally:
                source.close()


if __name__ == "__main__":
    unittest.main()
