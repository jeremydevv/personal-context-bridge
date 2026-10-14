import tempfile
import unittest
from pathlib import Path

from personal_context.notes_collect import PARTITIONS, parse_notes_snapshot
from personal_context.store import Store


class NotesCollectorTests(unittest.TestCase):
    timestamp = "2026-10-01T00:00:00Z"

    def snapshot(self):
        return {"success": True, "count": 2, "missingBodies": 1, "notes": [
            {"id": "note-1", "title": "First", "body": "first synthetic body",
             "folder": "Work", "createdAt": self.timestamp, "modifiedAt": self.timestamp,
             "contentAvailable": True},
            {"id": "note-2", "title": "Locked", "body": "", "folder": "Personal",
             "createdAt": self.timestamp, "modifiedAt": self.timestamp,
             "contentAvailable": False},
        ]}

    def test_complete_snapshot_and_tombstone(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "archive.sqlite3")
            try:
                batches, counts = parse_notes_snapshot(self.snapshot(), self.timestamp)
                self.assertEqual(PARTITIONS, len(batches))
                self.assertEqual({"notes": 2, "missing_bodies": 1}, counts)
                for batch in batches:
                    store.ingest(batch)
                self.assertIn("first synthetic body", store.get("note", "note-1")["body"])

                second = self.snapshot()
                second["notes"].pop()
                second["count"] = 1
                second["missingBodies"] = 0
                updated, _ = parse_notes_snapshot(second, "2026-10-02T00:00:00Z")
                for batch in updated:
                    store.ingest(batch)
                self.assertIsNone(store.get("note", "note-2"))
                self.assertEqual(2, store.version_count("note", "note-2"))
            finally:
                store.close()

    def test_incomplete_snapshot_cannot_delete_records(self):
        snapshot = self.snapshot()
        snapshot["count"] = 3
        with self.assertRaisesRegex(ValueError, "incomplete"):
            parse_notes_snapshot(snapshot, self.timestamp)
        snapshot = self.snapshot()
        snapshot["notes"][1]["id"] = "note-1"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_notes_snapshot(snapshot, self.timestamp)


if __name__ == "__main__":
    unittest.main()
