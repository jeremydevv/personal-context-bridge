import tempfile
import unittest
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from personal_context.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "context.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def batch(self, records, collected_at="2026-09-30T20:00:00Z"):
        return {
            "schema": 1,
            "source": "apple-pim",
            "kind": "calendar",
            "scope": "calendar:personal",
            "collected_at": collected_at,
            "complete": True,
            "records": records,
        }

    def event(self, title="Dentist"):
        return {
            "id": "event-1",
            "title": title,
            "start": "2026-10-02T14:00:00Z",
            "end": "2026-10-02T15:00:00Z",
            "body": "Bring insurance card",
            "payload": {"calendar": "Personal", "location": "Clinic"},
        }

    def test_import_is_idempotent_and_searchable(self):
        self.store.ingest(self.batch([self.event()]))
        self.store.ingest(self.batch([self.event()]))
        self.assertEqual(1, len(self.store.search("Dentist")))
        self.assertEqual(1, self.store.version_count("calendar", "event-1"))
        self.assertEqual("2026-09-30T20:00:00Z", self.store.last_sync("calendar"))

    def test_new_record_does_not_scan_fts_for_a_nonexistent_prior_entry(self):
        statements = []
        self.store.db.set_trace_callback(statements.append)
        try:
            self.store.ingest(self.batch([self.event()]))
        finally:
            self.store.db.set_trace_callback(None)
        self.assertFalse(any("DELETE FROM records_fts" in statement for statement in statements))
        self.assertEqual(["event-1"], [row["id"] for row in self.store.search("Dentist")])

    def test_question_words_do_not_hide_matching_personal_records(self):
        self.store.ingest(self.batch([{"id": "tennis", "title": "Tennis prototype",
                                      "body": "Discussed the movement model", "payload": {}}]))
        found = self.store.search("What did we discuss about the tennis prototype?")
        self.assertEqual(["tennis"], [row["id"] for row in found])

    def test_search_uses_bounded_partial_match_when_no_record_has_every_term(self):
        self.store.ingest(self.batch([{"id": "roadmap", "title": "Tennis roadmap",
                                      "body": "Movement model", "payload": {}}]))
        found = self.store.search("tennis prototype roadmap")
        self.assertEqual(["roadmap"], [row["id"] for row in found])

    def test_changed_record_adds_version(self):
        self.store.ingest(self.batch([self.event()]))
        self.store.ingest(self.batch([self.event("Dentist rescheduled")], "2026-10-01T20:00:00Z"))
        self.assertEqual(2, self.store.version_count("calendar", "event-1"))
        self.assertEqual("Dentist rescheduled", self.store.get("calendar", "event-1")["title"])

    def test_complete_scan_tombstones_missing_record_but_keeps_history(self):
        self.store.ingest(self.batch([self.event()]))
        self.store.ingest(self.batch([], "2026-10-01T20:00:00Z"))
        self.assertEqual([], self.store.search("Dentist"))
        self.assertEqual(2, self.store.version_count("calendar", "event-1"))
        self.assertTrue(self.store.get("calendar", "event-1", include_deleted=True)["deleted"])

    def test_incomplete_scan_does_not_delete_missing_record(self):
        self.store.ingest(self.batch([self.event()]))
        partial = self.batch([], "2026-10-01T20:00:00Z")
        partial["complete"] = False
        self.store.ingest(partial)
        self.assertEqual(1, len(self.store.search("Dentist")))

    def test_older_retry_cannot_resurrect_a_deleted_record(self):
        self.store.ingest(self.batch([self.event()], "2026-10-01T00:00:00Z"))
        self.store.ingest(self.batch([], "2026-10-02T00:00:00Z"))
        self.store.ingest(self.batch([self.event()], "2026-10-01T12:00:00Z"))
        self.assertIsNone(self.store.get("calendar", "event-1"))
        self.assertEqual(2, self.store.version_count("calendar", "event-1"))
        self.assertEqual("2026-10-02T00:00:00Z", self.store.last_sync("calendar"))

    def test_upcoming_uses_start_time_and_excludes_deleted(self):
        self.store.ingest(self.batch([self.event()]))
        self.assertEqual(1, len(self.store.upcoming("2026-10-01T00:00:00Z", "2026-10-04T00:00:00Z")))
        self.assertEqual([], self.store.upcoming("2026-10-03T00:00:00Z", "2026-10-04T00:00:00Z"))

    def test_open_reminders_includes_no_due_date_and_excludes_completed_or_deleted(self):
        batch = {"schema": 1, "source": "apple-pim", "kind": "reminder",
                 "scope": "reminder:list", "collected_at": "2026-10-01T00:00:00Z",
                 "complete": True, "records": [
                     {"id": "due", "title": "Due", "start": "2026-10-03T00:00:00Z",
                      "payload": {"isCompleted": False}},
                     {"id": "undated", "title": "Undated", "payload": {"isCompleted": False}},
                     {"id": "done", "title": "Done", "payload": {"isCompleted": True}},
                     {"id": "removed", "title": "Removed", "payload": {"isCompleted": False}},
                 ]}
        self.store.ingest(batch)
        batch["collected_at"] = "2026-10-02T00:00:00Z"
        batch["records"] = batch["records"][:-1]
        self.store.ingest(batch)
        total, count_only = self.store.open_reminders()
        self.assertEqual(2, total)
        self.assertEqual([], count_only)
        total, first = self.store.open_reminders(limit=1, include_items=True)
        self.assertEqual(2, total)
        self.assertEqual(["due"], [row["id"] for row in first])
        self.assertNotIn("body", first[0])
        _, second = self.store.open_reminders(limit=1, offset=1, include_items=True)
        self.assertEqual(["undated"], [row["id"] for row in second])

    def test_health_counts_stale_scopes_without_record_content(self):
        self.store.ingest(self.batch([self.event()]))
        result = self.store.health(datetime(2026, 10, 3, tzinfo=timezone.utc))
        self.assertEqual(1, result["sources"]["calendar"]["active_records"])
        self.assertEqual(1, result["sources"]["calendar"]["stale_scopes"])
        self.assertEqual(0, result["sources"]["note"]["scopes"])
        self.assertNotIn("Dentist", str(result))

    def test_health_flags_low_server_disk_space(self):
        usage = namedtuple("Usage", "total used free")(30 * 1024**3, 20 * 1024**3, 10 * 1024**3)
        with patch("personal_context.store.shutil.disk_usage", return_value=usage):
            result = self.store.health(datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.assertTrue(result["storage"]["low_space"])
        self.assertGreater(result["storage"]["archive_bytes"], 0)

    def test_calendar_inventory_records_drift_without_indexing_ids(self):
        def inventory(ids, when):
            return {"schema": 1, "source": "apple-pim", "kind": "inventory",
                    "scope": "calendar", "collected_at": when, "complete": True,
                    "records": [{"id": identifier, "title": identifier} for identifier in ids]}
        first = inventory(["calendar-a", "calendar-b"], "2026-10-01T00:00:00Z")
        second = inventory(["calendar-b", "calendar-c"], "2026-10-02T00:00:00Z")
        self.store.ingest(first)
        baseline = self.store.health(datetime(2026, 10, 2, tzinfo=timezone.utc))["sources"]["calendar"]["inventory"]
        self.assertEqual(0, baseline["added_last_scan"])
        self.store.ingest(second)
        self.store.ingest(first)
        drift = self.store.health(datetime(2026, 10, 2, tzinfo=timezone.utc))["sources"]["calendar"]["inventory"]
        self.assertEqual(2, drift["current_sources"])
        self.assertEqual(1, drift["added_last_scan"])
        self.assertEqual(1, drift["missing_sources"])
        self.assertEqual([], self.store.search("calendar-a"))

    def test_reminder_inventory_tracks_missing_lists(self):
        def inventory(ids, when):
            return {"schema": 1, "source": "apple-pim", "kind": "inventory",
                    "scope": "reminder", "collected_at": when, "complete": True,
                    "records": [{"id": identifier, "title": identifier} for identifier in ids]}
        self.store.ingest(inventory(["one", "two"], "2026-10-01T00:00:00Z"))
        self.store.ingest(inventory(["one"], "2026-10-02T00:00:00Z"))
        report = self.store.health(datetime(2026, 10, 2, tzinfo=timezone.utc))["sources"]["reminder"]
        self.assertEqual(1, report["inventory"]["current_sources"])
        self.assertEqual(1, report["inventory"]["missing_sources"])

    def test_mail_inventory_tracks_missing_mailboxes(self):
        def inventory(ids, when):
            return {"schema": 1, "source": "apple-pim", "kind": "inventory",
                    "scope": "mail", "collected_at": when, "complete": True,
                    "records": [{"id": identifier, "title": identifier} for identifier in ids]}
        self.store.ingest(inventory(["inbox", "sent"], "2026-10-01T00:00:00Z"))
        self.store.ingest(inventory(["inbox"], "2026-10-02T00:00:00Z"))
        report = self.store.health(datetime(2026, 10, 2, tzinfo=timezone.utc))["sources"]["mail"]
        self.assertEqual(1, report["inventory"]["current_sources"])
        self.assertEqual(1, report["inventory"]["missing_sources"])


if __name__ == "__main__":
    unittest.main()
