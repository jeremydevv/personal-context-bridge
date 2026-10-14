import tempfile
import unittest
import sqlite3
from pathlib import Path

from personal_context.service import QueryService
from personal_context.store import Store


class ServiceTests(unittest.TestCase):
    def test_query_service_cannot_modify_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "store.sqlite3"
            store = Store(db)
            store.ingest({"schema": 1, "source": "apple-pim", "kind": "calendar",
                          "scope": "calendar:one", "collected_at": "2026-10-01T00:00:00Z",
                          "complete": True, "records": [{"id": "one", "title": "Kept"}]})
            store.close()
            service = QueryService(db)
            with self.assertRaises(sqlite3.OperationalError):
                service._use(lambda reader: reader.db.execute("DELETE FROM records"))
            self.assertEqual("Kept", service.get("calendar", "one")["record"]["title"])

    def test_upcoming_normalizes_offset_window(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "store.sqlite3"
            store = Store(db)
            store.ingest({"schema": 1, "source": "apple-pim", "kind": "calendar",
                          "scope": "calendar:one", "collected_at": "2026-10-01T00:00:00Z",
                          "complete": True,
                          "records": [
                              {"id": "inside", "title": "Inside", "start": "2026-10-02T14:00:00Z"},
                              {"id": "outside", "title": "Outside", "start": "2026-10-02T15:00:00Z"},
                          ]})
            store.close()
            service = QueryService(db)
            result = service.upcoming("2026-10-02T10:00:00-04:00", "2026-10-02T11:00:00-04:00")
            self.assertEqual(["inside"], [row["id"] for row in result["results"]])
            with self.assertRaises(ValueError):
                service.upcoming("2026-10-02T10:00:00", "2026-10-02T11:00:00")

    def test_search_marks_partial_term_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "store.sqlite3"
            store = Store(db)
            store.ingest({"schema": 1, "source": "apple-pim", "kind": "calendar",
                          "scope": "calendar:one", "collected_at": "2026-10-01T00:00:00Z",
                          "complete": True,
                          "records": [{"id": "one", "title": "Tennis roadmap", "body": "Movement model"}]})
            store.close()
            result = QueryService(db).search("tennis prototype roadmap")
            self.assertEqual("any_term", result["match_mode"])
            self.assertEqual("one", result["results"][0]["id"])

    def test_search_time_window_filters_source_records_and_rejects_naive_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "store.sqlite3"
            store = Store(db)
            store.ingest({"schema": 1, "source": "apple-local", "kind": "message",
                          "scope": "message:test", "collected_at": "2026-10-03T00:00:00Z",
                          "complete": True, "records": [
                              {"id": "inside", "title": "Tennis planning", "start": "2026-10-02T14:00:00Z"},
                              {"id": "outside", "title": "Tennis planning", "start": "2026-09-20T14:00:00Z"},
                          ]})
            store.close()
            service = QueryService(db)
            result = service.search("tennis", kind="message",
                                    start="2026-10-02T10:00:00-04:00",
                                    end="2026-10-02T11:00:00-04:00")
            self.assertEqual(["inside"], [row["id"] for row in result["results"]])
            self.assertEqual({"start": "2026-10-02T14:00:00.000000Z",
                              "end": "2026-10-02T15:00:00.000000Z"}, result["time_window"])
            with self.assertRaises(ValueError):
                service.search("tennis", start="2026-10-02T14:00:00", end="2026-10-03T00:00:00Z")
            with self.assertRaises(ValueError):
                service.search("tennis", start="2026-10-02T14:00:00Z")

    def test_timeline_orders_cross_source_activity_and_bounds_snippets(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "store.sqlite3"
            store = Store(db)
            for kind, source, identifier, started in (
                ("calendar", "apple-pim", "event", "2026-09-30T14:00:00Z"),
                ("message", "apple-local", "message", "2026-09-30T16:00:00Z"),
                ("message", "apple-local", "edge", "2026-09-30T00:00:00.123456Z"),
                ("message", "apple-local", "older", "2026-09-29T16:00:00Z"),
            ):
                store.ingest({"schema": 1, "source": source, "kind": kind,
                              "scope": kind + ":test", "collected_at": "2026-10-01T00:00:00Z",
                              "complete": False,
                              "records": [{"id": identifier, "title": identifier,
                                           "body": "private " * 100, "start": started, "payload": {}}]})
            store.close()
            service = QueryService(db)
            result = service.timeline("2026-09-30T00:00:00Z", "2026-10-01T00:00:00Z")
            self.assertEqual(["message", "event", "edge"], [row["id"] for row in result["results"]])
            self.assertTrue(all(len(row["body"]) <= 200 for row in result["results"]))
            self.assertEqual("2026-10-01T00:00:00Z", result["last_synced_at"])
            filtered = service.timeline("2026-09-30T00:00:00Z", "2026-10-01T00:00:00Z", kind="calendar")
            self.assertEqual(["event"], [row["id"] for row in filtered["results"]])

    def test_search_returns_brief_results_and_freshness(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "store.sqlite3"
            store = Store(db)
            store.ingest({
                "schema": 1, "source": "apple-pim", "kind": "calendar",
                "scope": "calendar:personal", "collected_at": "2026-09-30T20:00:00Z",
                "complete": True, "records": [{"id": "one", "title": "Doctor appointment",
                    "body": "Private details " * 100, "start": "2026-10-02T14:00:00Z",
                    "payload": {"location": "Clinic"}}],
            })
            store.close()
            service = QueryService(db)
            result = service.search("Doctor")
            self.assertEqual("2026-09-30T20:00:00Z", result["last_synced_at"])
            self.assertEqual("Doctor appointment", result["results"][0]["title"])
            self.assertNotIn("payload", result["results"][0])
            self.assertLessEqual(len(result["results"][0]["body"]), 200)
            self.assertEqual("Clinic", service.get("calendar", "one")["record"]["payload"]["location"])


if __name__ == "__main__":
    unittest.main()
