import tempfile
import unittest
from pathlib import Path

from personal_context.service import QueryService
from personal_context.store import Store


STAMP = "2026-10-02T00:00:00Z"
START = "2026-10-01T00:00:00Z"
END = "2026-10-03T00:00:00Z"


class ContactActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "archive.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def ingest(self, kind, records, when=STAMP, complete=True):
        self.store.ingest({"schema": 1, "source": "apple-local" if kind != "mail" else "apple-pim",
                           "kind": kind, "scope": kind + ":test", "collected_at": when,
                           "complete": complete, "records": records})

    def contact(self, ident="alice", email="Alice@Example.com", phone="+1 (555) 010-0000"):
        return {"id": ident, "title": "Alice", "payload": {
            "emails": [{"value": email}], "phones": [{"value": phone}]}}

    def test_exact_identifiers_link_mail_and_group_messages_with_source_ids(self):
        self.ingest("contact", [self.contact()])
        self.ingest("mail", [{"id": "mail-1", "title": "Hello", "start": STAMP,
                              "payload": {"senderAddress": "ALICE@example.com", "to": [], "cc": []}}])
        self.ingest("message", [{"id": "msg-1", "title": "Text", "start": STAMP,
                                 "payload": {"sender": "me", "fromMe": True,
                                             "chats": [{"participants": ["+15550100000", "+15550100001"]}]}}])
        result = QueryService(self.path).contact_activity("alice", START, END)
        self.assertEqual({("mail", "mail-1"), ("message", "msg-1")},
                         {(row["kind"], row["id"]) for row in result["results"]})
        self.assertEqual(["sender"], next(row["roles"] for row in result["results"] if row["kind"] == "mail"))
        self.assertTrue(next(row["group_chat"] for row in result["results"] if row["kind"] == "message"))
        self.assertNotIn("body", str(result))

    def test_shared_contact_identifier_is_ambiguous_and_yields_no_activity(self):
        self.ingest("contact", [self.contact(), self.contact("other", email="alice@example.com", phone="2125550000")])
        self.ingest("mail", [{"id": "mail-1", "title": "Hello", "start": STAMP,
                              "payload": {"senderAddress": "alice@example.com"}}])
        result = QueryService(self.path).contact_activity("alice", START, END)
        self.assertEqual([], result["results"])
        self.assertEqual(["email:alice@example.com"], result["ambiguous_identifiers"])

    def test_tombstone_and_changed_identifier_update_activity(self):
        self.ingest("contact", [self.contact()])
        self.ingest("mail", [{"id": "mail-1", "title": "Hello", "start": STAMP,
                              "payload": {"senderAddress": "alice@example.com"}}])
        self.assertEqual(1, len(QueryService(self.path).contact_activity("alice", START, END)["results"]))
        self.ingest("mail", [{"id": "mail-1", "title": "Changed", "start": STAMP,
                              "payload": {"senderAddress": "bob@example.com"}}], "2026-10-02T01:00:00Z")
        self.assertEqual([], QueryService(self.path).contact_activity("alice", START, END)["results"])
        self.ingest("mail", [], "2026-10-02T02:00:00Z")
        self.assertEqual([], QueryService(self.path).contact_activity("alice", START, END)["results"])

    def test_existing_archive_requires_atomic_rebuild_before_query(self):
        self.ingest("contact", [self.contact()])
        self.ingest("mail", [{"id": "mail-1", "title": "Hello", "start": STAMP,
                              "payload": {"senderAddress": "alice@example.com"}}])
        self.store.db.execute("DROP TABLE record_identifiers")
        self.store.db.execute("DROP TABLE derived_index_meta")
        self.store.db.commit()
        self.store.close()
        self.store = Store(self.path)
        with self.assertRaisesRegex(RuntimeError, "rebuild"):
            QueryService(self.path).contact_activity("alice", START, END)
        self.store.rebuild_record_identifiers()
        self.assertEqual(["mail-1"], [row["id"] for row in QueryService(self.path).contact_activity("alice", START, END)["results"]])

    def test_rebuild_failure_preserves_previous_ready_index(self):
        self.ingest("contact", [self.contact()])
        self.ingest("mail", [{"id": "mail-1", "title": "Hello", "start": STAMP,
                              "payload": {"senderAddress": "alice@example.com"}}])
        self.store.db.execute("UPDATE records SET payload='{' WHERE kind='mail' AND id='mail-1'")
        self.store.db.commit()
        with self.assertRaises(ValueError):
            self.store.rebuild_record_identifiers()
        self.assertEqual(["mail-1"], [row["id"] for row in QueryService(self.path).contact_activity("alice", START, END)["results"]])

    def test_missing_readiness_metadata_never_trusts_existing_table(self):
        self.ingest("contact", [self.contact()])
        self.ingest("mail", [{"id": "mail-1", "title": "Hello", "start": STAMP,
                              "payload": {"senderAddress": "alice@example.com"}}])
        self.store.db.execute("DROP TABLE derived_index_meta")
        self.store.db.commit()
        self.store.close()
        self.store = Store(self.path)
        with self.assertRaisesRegex(RuntimeError, "rebuild"):
            QueryService(self.path).contact_activity("alice", START, END)

    def test_name_only_and_malformed_identifiers_do_not_link(self):
        self.ingest("contact", [self.contact(email="bad address", phone="123")])
        self.ingest("mail", [{"id": "mail-1", "title": "Alice", "start": STAMP,
                              "payload": {"senderAddress": "alice@example.com"}}])
        self.ingest("message", [{"id": "msg-1", "title": "Alice", "start": STAMP,
                                 "payload": {"sender": "Alice", "chats": []}}])
        self.assertEqual([], QueryService(self.path).contact_activity("alice", START, END)["results"])


if __name__ == "__main__":
    unittest.main()
