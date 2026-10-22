import io
import json
import tempfile
import unittest
import fcntl
import threading
import time
from pathlib import Path
from unittest.mock import patch

from personal_context.cli import main


class CliSecurityTests(unittest.TestCase):
    def test_ingestion_waits_for_other_ingestion_before_opening_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "archive.sqlite3"
            lock = Path(str(database) + ".ingest.lock").open("ab")
            fcntl.flock(lock, fcntl.LOCK_EX)
            payload = {"schema": 1, "source": "apple-pim", "kind": "calendar",
                       "scope": "test", "collected_at": "2026-10-01T00:00:00Z",
                       "complete": False, "records": [{"id": "fictional", "title": "Fixture"}]}
            failures = []
            def ingest():
                try:
                    main(["ingest-stdin", "--db", str(database)])
                except BaseException as exc:
                    failures.append(exc)
            with patch("personal_context.cli.require_archive_key"), \
                 patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                 patch("sys.stdout", new_callable=io.StringIO):
                thread = threading.Thread(target=ingest)
                thread.start()
                try:
                    time.sleep(0.2)
                    self.assertFalse(database.exists(), "ingestion opened the archive while another writer held its gate")
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    lock.close()
                    thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
            self.assertEqual([], failures)
            from personal_context.store import Store
            store = Store(database, read_only=True)
            try:
                self.assertEqual("Fixture", store.get("calendar", "fictional")["title"])
            finally:
                store.close()

    def test_attachment_inventory_can_read_during_ingestion(self):
        from personal_context.store import Store
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "archive.sqlite3"
            store = Store(database)
            try:
                store.db.execute("BEGIN IMMEDIATE")
                with patch("personal_context.cli.require_archive_key"), \
                     patch("sys.stdout", new_callable=io.StringIO) as output:
                    code = main(["attachment-index", "--db", str(database)])
                self.assertEqual(0, code)
                self.assertEqual([], json.loads(output.getvalue())["attachments"])
            finally:
                store.db.rollback()
                store.close()

    def test_all_reminders_selects_visible_lists_and_queues_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(json.dumps({"calendar_ids": [], "reminder_ids": [], "all_reminders": True,
                                          "remote_host": "ubuntu-box", "remote_project": "/tmp/context",
                                          "spool_dir": str(Path(directory) / "spool")}))
            listing = {"success": True, "lists": [{"id": "one"}, {"id": "two"}]}
            with patch("personal_context.cli.run_cli", return_value=listing), \
                 patch("personal_context.cli.collect_batches", return_value=[]) as collect, \
                 patch("sys.stdout", new_callable=io.StringIO):
                main(["collect", "--config", str(config)])
            self.assertEqual(["one", "two"], collect.call_args.args[2])
            queued = [json.loads(path.read_text()) for path in (Path(directory) / "spool").glob("*.json")]
            self.assertEqual(1, len(queued))
            self.assertEqual("reminder", queued[0]["scope"])

    def test_all_calendars_selects_current_ids_at_collection_time(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(json.dumps({"calendar_ids": [], "reminder_ids": [], "all_calendars": True,
                                          "remote_host": "ubuntu-box", "remote_project": "/tmp/context",
                                          "spool_dir": str(Path(directory) / "spool")}))
            listing = {"success": True, "calendars": [{"id": "one"}, {"id": "two"}]}
            with patch("personal_context.cli.run_cli", return_value=listing), \
                 patch("personal_context.cli.collect_batches", return_value=[]) as collect:
                with patch("sys.stdout", new_callable=io.StringIO):
                    main(["collect", "--config", str(config)])
            self.assertEqual(["one", "two"], collect.call_args.args[1])

    def test_ingest_envelope_replays_without_duplicate_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "archive.sqlite3"
            def batch(scope, record_id):
                return {"schema": 1, "source": "apple-pim", "kind": "calendar",
                        "scope": scope, "collected_at": "2026-09-30T20:00:00Z",
                        "complete": True, "records": [{"id": record_id, "title": record_id}]}
            payload = {"schema": 1, "batches": [batch("one", "a"), batch("two", "b")]}
            with patch("personal_context.cli.require_archive_key"), patch("sys.stdin", io.StringIO(json.dumps(payload))):
                with patch("sys.stdout", new_callable=io.StringIO):
                    main(["ingest-stdin", "--db", str(database)])
            with patch("personal_context.cli.require_archive_key"), patch("sys.stdin", io.StringIO(json.dumps(payload))):
                with patch("sys.stdout", new_callable=io.StringIO):
                    main(["ingest-stdin", "--db", str(database)])
            from personal_context.store import Store
            store = Store(database)
            try:
                self.assertEqual(2, store.db.execute("SELECT COUNT(*) FROM records").fetchone()[0])
                self.assertEqual(2, store.db.execute("SELECT COUNT(*) FROM versions").fetchone()[0])
            finally:
                store.close()

    def test_server_refuses_ingest_without_archive_key(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "archive.sqlite3"
            payload = {"schema": 1, "source": "apple-pim", "kind": "calendar",
                       "scope": "calendar:test", "collected_at": "2026-09-30T20:00:00Z",
                       "complete": True, "records": []}
            with patch.dict("os.environ", {}, clear=True), patch("sys.stdin", io.StringIO(json.dumps(payload))):
                with self.assertRaisesRegex(RuntimeError, "key"):
                    main(["ingest-stdin", "--db", str(database)])
            self.assertFalse(database.exists())

    def test_mail_snapshot_uses_bounded_retryable_envelopes(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(json.dumps({"calendar_ids": [], "reminder_ids": [],
                                          "all_mailboxes": True, "remote_host": "ubuntu-box",
                                          "remote_project": "/tmp/context",
                                          "spool_dir": str(Path(directory) / "spool")}))
            mailbox = {"localMailboxId": 1, "mailboxUrl": "synthetic://mailbox", "messageCount": 0}
            batches = [{"schema": 1, "source": "apple-pim", "kind": "mail",
                        "scope": "mail:synthetic:bucket:" + str(index),
                        "collected_at": "2026-10-01T00:00:00Z", "complete": True,
                        "records": []} for index in range(32)]
            sent = []
            with patch("personal_context.cli.request_mail_refresh"), \
                 patch("personal_context.cli.list_mailboxes", return_value=[mailbox]), \
                 patch("personal_context.cli.export_mailbox", return_value=(batches, 0)), \
                 patch("personal_context.cli.deliver_ssh", side_effect=lambda config, payload, timeout: sent.append(json.loads(payload))), \
                 patch("sys.stdout", new_callable=io.StringIO):
                main(["mail-sync", "--config", str(config)])
            self.assertEqual(9, len(sent))
            self.assertTrue(all(len(item["batches"]) == 4 for item in sent[:8]))
            self.assertEqual("mail", sent[-1]["scope"])
            self.assertEqual(["synthetic://mailbox"], [record["id"] for record in sent[-1]["records"]])
            self.assertEqual([], list((Path(directory) / "spool/mail-sync").glob("*.json")))

    def test_health_check_fails_on_stale_scopes(self):
        from personal_context.store import Store
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "archive.sqlite3"
            store = Store(database)
            store.ingest({"schema": 1, "source": "apple-pim", "kind": "calendar",
                          "scope": "calendar:old", "collected_at": "2020-01-01T00:00:00Z",
                          "complete": True, "records": []})
            store.close()
            with patch("personal_context.cli.require_archive_key"), \
                 patch("sys.stdout", new_callable=io.StringIO):
                exit_code = main(["health", "--db", str(database), "--fail-on-stale"])
            self.assertEqual(2, exit_code)

    def test_health_can_read_while_ingestion_holds_write_transaction(self):
        from personal_context.store import Store
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "archive.sqlite3"
            store = Store(database)
            try:
                store.db.execute("BEGIN IMMEDIATE")
                with patch("personal_context.cli.require_archive_key"), \
                     patch("sys.stdout", new_callable=io.StringIO) as output:
                    code = main(["health", "--db", str(database)])
                self.assertEqual(0, code)
                self.assertEqual(0, json.loads(output.getvalue())["sources"]["mail"]["active_records"])
            finally:
                store.db.rollback()
                store.close()

    def test_health_check_fails_on_calendar_inventory_drift(self):
        from personal_context.store import Store
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "archive.sqlite3"
            store = Store(database)
            def snapshot(ids, timestamp):
                return {"schema": 1, "source": "apple-pim", "kind": "inventory",
                        "scope": "calendar", "collected_at": timestamp,
                        "complete": True, "records": [{"id": identifier, "title": identifier} for identifier in ids]}
            store.ingest(snapshot(["a", "b"], "2026-10-01T00:00:00Z"))
            store.ingest(snapshot(["b"], "2026-10-02T00:00:00Z"))
            store.close()
            with patch("personal_context.cli.require_archive_key"), \
                 patch("sys.stdout", new_callable=io.StringIO):
                code = main(["health", "--db", str(database), "--fail-on-inventory-drift"])
            self.assertEqual(2, code)


if __name__ == "__main__":
    unittest.main()
