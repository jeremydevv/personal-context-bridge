import tempfile
import unittest
from pathlib import Path

from personal_context.contacts_collect import parse_contacts_snapshot
from personal_context.store import Store


class ContactsCollectorTests(unittest.TestCase):
    timestamp = "2026-10-01T18:00:00Z"

    def snapshot(self):
        return {"success": True, "count": 2, "contacts": [
            {"id": "person-1", "name": "Alice Example", "firstName": "Alice",
             "lastName": "Example", "organization": "Example Lab", "note": "Project contact",
             "emails": [{"label": "work", "value": "alice@example.com"}],
             "phones": [{"label": "mobile", "value": "+15550100"}],
             "addresses": [], "urls": [], "relatedNames": [],
             "instantMessages": [], "socialProfiles": []},
            {"id": "person-2", "name": "Bob Example", "firstName": "Bob",
             "lastName": "Example", "organization": "", "note": "",
             "emails": [], "phones": [], "addresses": [], "urls": [],
             "relatedNames": [], "instantMessages": [], "socialProfiles": []},
        ]}

    def test_complete_contact_snapshot_is_searchable_and_tombstones_missing_people(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "archive.sqlite3")
            try:
                batches, counts = parse_contacts_snapshot(self.snapshot(), self.timestamp)
                self.assertEqual({"contacts": 2}, counts)
                self.assertTrue(all(batch["complete"] for batch in batches))
                for batch in batches:
                    store.ingest(batch)
                self.assertIn("alice@example.com", store.get("contact", "person-1")["body"])
                self.assertEqual("Alice Example", store.get("contact", "person-1")["title"])

                next_snapshot = self.snapshot()
                next_snapshot["contacts"].pop()
                next_snapshot["count"] = 1
                later, _ = parse_contacts_snapshot(next_snapshot, "2026-10-02T18:00:00Z")
                for batch in later:
                    store.ingest(batch)
                self.assertIsNone(store.get("contact", "person-2"))
            finally:
                store.close()

    def test_incomplete_or_duplicate_contact_snapshot_cannot_delete_records(self):
        snapshot = self.snapshot()
        snapshot["count"] = 3
        with self.assertRaisesRegex(ValueError, "incomplete"):
            parse_contacts_snapshot(snapshot, self.timestamp)
        snapshot = self.snapshot()
        snapshot["contacts"][1]["id"] = "person-1"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_contacts_snapshot(snapshot, self.timestamp)


if __name__ == "__main__":
    unittest.main()
