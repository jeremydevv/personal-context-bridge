import unittest

from personal_context.collect import collect_batches, collect_recent_calendar, collect_contacts, _record


class CollectorTests(unittest.TestCase):
    def test_contact_snapshot_searches_full_details_and_is_stable(self):
        calls = []
        def run(args):
            calls.append(args)
            if args[1] == "list":
                return {"success": True, "contacts": [{"id": "c1"}]}
            return {"success": True, "contact": {"id": "c1", "fullName": "Ada Example",
                    "emails": [{"label": "work", "value": "ada@example.com"}],
                    "phones": [{"label": "mobile", "value": "555-1234"}], "notes": "Met at conference"}}
        batch = collect_contacts(run, "2026-09-30T20:00:00Z")
        self.assertEqual("contact", batch["kind"])
        self.assertEqual("contacts:all", batch["scope"])
        self.assertIn("ada@example.com", batch["records"][0]["body"])
        self.assertEqual(["contacts-cli", "get", "--id", "c1"], calls[1])

    def test_contact_snapshot_rejects_truncation(self):
        with self.assertRaisesRegex(ValueError, "limit"):
            collect_contacts(lambda _: {"success": True, "contacts": [{"id": "a"}, {"id": "b"}]},
                             "2026-09-30T20:00:00Z", limit=2)

    def test_contact_snapshot_rejects_wrong_detail(self):
        def run(args):
            return ({"success": True, "contacts": [{"id": "a"}]} if args[1] == "list"
                    else {"success": True, "contact": {"id": "b"}})
        with self.assertRaisesRegex(ValueError, "incomplete"):
            collect_contacts(run, "2026-09-30T20:00:00Z")

    def test_calendar_unordered_eventkit_fields_are_stable(self):
        base = {"id": "event", "title": "Meeting", "startDate": "2026-09-30T15:00:00Z"}
        first = dict(base, attendees=[{"name": "B"}, {"name": "A"}], alarms=[{"minutes": 10}, {"minutes": 5}])
        second = dict(base, attendees=list(reversed(first["attendees"])), alarms=list(reversed(first["alarms"])))
        self.assertEqual(_record("calendar", first), _record("calendar", second))

    def test_only_explicitly_allowed_sources_are_collected(self):
        calls = []

        def run(args):
            calls.append(args)
            if args == ["calendar-cli", "list"]:
                return {"success": True, "calendars": [
                    {"id": "personal", "title": "Personal"}, {"id": "secret", "title": "Secret"}]}
            if args == ["reminder-cli", "lists"]:
                return {"success": True, "lists": [
                    {"id": "tasks", "title": "Tasks"}, {"id": "hidden", "title": "Hidden"}]}
            if args[0] == "calendar-cli":
                return {"success": True, "events": [{
                    "id": "evt-1", "title": "Meeting", "startDate": "2026-10-02T14:00:00Z",
                    "endDate": "2026-10-02T15:00:00Z", "calendarId": "personal", "notes": "Agenda"}]}
            return {"success": True, "reminders": [{
                "id": "rem-1", "title": "Pay bill", "listId": "tasks", "dueDate": "2026-10-03"}]}

        batches = collect_batches(run, ["personal"], ["tasks"], "2025-01-01", "2027-12-31", "2026-09-30T20:00:00Z")
        self.assertEqual(["calendar:personal:2025-2027", "reminder:tasks"], [b["scope"] for b in batches])
        self.assertEqual("Agenda", batches[0]["records"][0]["body"])
        self.assertTrue(all("secret" not in str(c) and "hidden" not in str(c) for c in calls))

    def test_refuses_empty_allowlist(self):
        with self.assertRaises(ValueError):
            collect_batches(lambda _: {}, [], [], "2000-01-01", "2100-12-31", "2026-09-30T20:00:00Z")

    def test_refuses_truncated_scan(self):
        def run(args):
            if args == ["calendar-cli", "list"]:
                return {"success": True, "calendars": [{"id": "personal", "title": "Personal"}]}
            return {"success": True, "events": [{"id": str(i), "title": "x", "startDate": "2026-10-02T14:00:00Z"} for i in range(2)]}

        with self.assertRaisesRegex(ValueError, "limit"):
            collect_batches(run, ["personal"], [], "2025-01-01", "2027-12-31", "2026-09-30T20:00:00Z", limit=2)

    def test_calendar_scans_in_three_year_windows(self):
        calls = []

        def run(args):
            calls.append(args)
            if args == ["calendar-cli", "list"]:
                return {"success": True, "calendars": [{"id": "personal", "title": "Personal"}]}
            if "2025-01-01" in args:
                return {"success": True, "events": [{"id": "one", "title": "Old event",
                    "calendarId": "personal", "startDate": "2026-10-02T14:00:00Z"}]}
            return {"success": True, "events": []}

        batches = collect_batches(run, ["personal"], [], "2025-01-01", "2030-12-31", "2026-09-30T20:00:00Z")
        self.assertEqual(["calendar:personal:2025-2027", "calendar:personal:2028-2030"],
                         [batch["scope"] for batch in batches])
        self.assertEqual(1, sum(len(batch["records"]) for batch in batches))
        event_calls = [call for call in calls if len(call) > 1 and call[1] == "events"]
        self.assertEqual(2, len(event_calls))

    def test_recent_calendar_keeps_full_scan_scope_and_cannot_delete_older_events(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from personal_context.store import Store

        def run(args):
            if args[1] == "list":
                return {"success": True, "calendars": [{"id": "personal"}]}
            return {"success": True, "events": [{"id": "new", "calendarId": "personal",
                    "title": "New", "startDate": "2026-10-02T14:00:00Z"}]}

        with TemporaryDirectory() as directory:
            store = Store(Path(directory) / "context.sqlite3")
            try:
                store.ingest({"schema": 1, "source": "apple-pim", "kind": "calendar",
                              "scope": "calendar:personal:2024-2026", "collected_at": "2026-09-30T00:00:00Z",
                              "complete": True, "records": [{"id": "older", "title": "Older",
                                                                  "start": "2024-01-01T00:00:00Z"}]})
                batches = collect_recent_calendar(run, ["personal"], "2026-09-01", "2026-11-01",
                                                  "1970-01-01", "2100-12-31", "2026-10-01T00:00:00Z")
                self.assertEqual(["calendar:personal:2024-2026"], [b["scope"] for b in batches])
                self.assertFalse(batches[0]["complete"])
                store.ingest(batches[0])
                self.assertIsNotNone(store.get("calendar", "older"))
                self.assertIsNotNone(store.get("calendar", "new|2026-10-02T14:00:00Z"))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
