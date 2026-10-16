import tempfile
import json
import subprocess
from unittest.mock import patch
import unittest
from pathlib import Path

from personal_context.notes_collect import PARTITIONS, parse_notes_snapshot, collect_notes
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

    def test_collector_restores_app_lifecycle_on_success_and_failure(self):
        # Mock only the macOS process boundary: Ubuntu cannot run osascript.
        for already_running in (False, True):
            for outcome in ("success", "error", "timeout", "malformed"):
                with self.subTest(already_running=already_running, outcome=outcome):
                    state = {"running": already_running}

                    def automation(args, **kwargs):
                        if "-e" in args:
                            script = args[-1]
                            if "quit()" in script:
                                state["running"] = False
                                return subprocess.CompletedProcess(args, 0, "", "")
                            return subprocess.CompletedProcess(args, 0,
                                                               str(state["running"]).lower(), "")
                        state["running"] = True
                        if outcome == "timeout":
                            raise subprocess.TimeoutExpired(args, 900)
                        return subprocess.CompletedProcess(
                            args, 1 if outcome == "error" else 0,
                            "invalid" if outcome == "malformed" else json.dumps(self.snapshot()),
                            "synthetic automation failure" if outcome == "error" else "")

                    with tempfile.TemporaryDirectory() as directory, patch.dict(
                            "os.environ", {"PERSONAL_CONTEXT_DATA_DIR": directory}), patch(
                            "personal_context.notes_collect.subprocess.run", side_effect=automation):
                        if outcome == "success":
                            _, counts = collect_notes()
                            self.assertEqual(counts, {"notes": 2, "missing_bodies": 1})
                        else:
                            expected = {"error": RuntimeError, "timeout": subprocess.TimeoutExpired,
                                        "malformed": ValueError}[outcome]
                            with self.assertRaises(expected):
                                collect_notes()
                        self.assertEqual(state["running"], already_running)

    def test_failed_state_probe_does_not_launch_or_close_notes(self):
        def automation(args, **kwargs):
            if "-e" not in args or "quit()" in args[-1]:
                self.fail("Must not collect or quit when the initial app state is unknown")
            return subprocess.CompletedProcess(args, 1, "", "probe failed")

        with tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"PERSONAL_CONTEXT_DATA_DIR": directory}), patch(
                "personal_context.notes_collect.subprocess.run", side_effect=automation):
            with self.assertRaises(RuntimeError):
                collect_notes()

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
