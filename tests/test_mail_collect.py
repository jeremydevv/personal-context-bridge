import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from personal_context.mail_collect import parse_export, recent_mailbox, PARTITIONS
from personal_context import mail_collect
from personal_context.store import Store


class MailCollectorTests(unittest.TestCase):
    mailbox = {"localMailboxId": 17, "mailboxUrl": "imap://account/INBOX", "messageCount": 2}
    timestamp = "2026-10-01T12:00:00Z"

    def test_refresh_requests_provider_fetch_without_quitting_mail(self):
        from subprocess import CompletedProcess
        with patch("personal_context.mail_collect.subprocess.run", return_value=CompletedProcess([], 0, "", "")) as run:
            mail_collect.request_mail_refresh()
        self.assertEqual([
            ["open", "-g", "-a", "Mail"],
            ["osascript", "-e", 'tell application "Mail" to check for new mail'],
        ], [call.args[0] for call in run.call_args_list])
        self.assertTrue(all(call.kwargs["timeout"] <= 60 for call in run.call_args_list))

    def test_failed_refresh_is_not_reported_as_successful_collection(self):
        from subprocess import CompletedProcess
        with patch("personal_context.mail_collect.subprocess.run", return_value=CompletedProcess([], 1, "", "private diagnostic")):
            with self.assertRaisesRegex(RuntimeError, "Mail refresh request failed") as error:
                mail_collect.request_mail_refresh()
        self.assertNotIn("private diagnostic", str(error.exception))

    def lines(self, footer=True):
        values = [
            {"type": "header", "mailboxRowid": 17, "count": 2, "totalInMailbox": 2},
            {"type": "message", "contentAvailable": True,
             "message": {"localId": 101, "messageId": "same@example.com", "subject": "First",
                         "senderAddress": "a@example.com", "content": "First body", "dateReceived": "2026-01-01T00:00:00Z"}},
            {"type": "message", "contentAvailable": False,
             "message": {"localId": 102, "messageId": "same@example.com", "subject": "Second",
                         "senderAddress": "b@example.com", "dateReceived": "2026-01-02T00:00:00Z"}},
        ]
        if footer:
            values.append({"type": "footer", "exported": 2, "missingBodies": 1})
        return [json.dumps(value) for value in values]

    def test_duplicate_rfc_ids_remain_distinct_and_bodies_are_honest(self):
        batches, missing = parse_export(self.lines(), self.mailbox, self.timestamp)
        records = [record for batch in batches for record in batch["records"]]
        self.assertEqual(PARTITIONS, len(batches))
        self.assertEqual(2, len(records))
        self.assertEqual(2, len({record["id"] for record in records}))
        self.assertEqual(1, missing)
        self.assertEqual([False, True], sorted(record["payload"]["contentAvailable"] for record in records))
        self.assertTrue(all(batch["complete"] for batch in batches))

    def test_missing_footer_cannot_mark_mailbox_complete(self):
        with self.assertRaisesRegex(ValueError, "complete snapshot"):
            parse_export(self.lines(footer=False), self.mailbox, self.timestamp)

    def test_inventory_count_mismatch_cannot_mark_mailbox_complete(self):
        lines = self.lines()
        header = json.loads(lines[0])
        header["totalInMailbox"] = 3
        lines[0] = json.dumps(header)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            parse_export(lines, self.mailbox, self.timestamp)

    def test_complete_partition_snapshots_tombstone_only_missing_local_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "synthetic.sqlite3")
            try:
                first, _ = parse_export(self.lines(), self.mailbox, self.timestamp)
                for batch in first:
                    store.ingest(batch)
                initial = [record for batch in first for record in batch["records"]]
                self.assertEqual(2, sum(store.get("mail", record["id"]) is not None for record in initial))

                second_lines = self.lines()
                second_lines[0] = json.dumps({"type": "header", "mailboxRowid": 17,
                                              "count": 1, "totalInMailbox": 1})
                second_lines.pop(2)
                second_lines[-1] = json.dumps({"type": "footer", "exported": 1, "missingBodies": 0})
                second, _ = parse_export(second_lines, self.mailbox, "2026-10-02T12:00:00Z")
                for batch in second:
                    store.ingest(batch)
                self.assertIsNotNone(store.get("mail", initial[0]["id"]))
                self.assertIsNone(store.get("mail", initial[1]["id"]))
                self.assertEqual(2, store.version_count("mail", initial[1]["id"]))
            finally:
                store.close()

    def test_recent_mail_uses_partial_existing_bucket_and_rejects_truncation(self):
        from subprocess import CompletedProcess
        summary = {"localId": 101, "messageId": "same@example.com", "subject": "First",
                   "dateReceived": "2026-10-01T11:00:00Z"}
        detail = dict(summary, content="Body")
        def fake_run(args, **kwargs):
            if args[1] == "messages":
                self.assertIn("--since", args)
                return CompletedProcess(args, 0, json.dumps({"success": True, "engine": "sqlite",
                                                           "messages": [summary]}), "")
            return CompletedProcess(args, 0, json.dumps({"success": True, "message": detail}), "")
        with patch("personal_context.mail_collect.subprocess.run", side_effect=fake_run):
            batches, missing = recent_mailbox(self.mailbox, "2026-09-28T00:00:00Z", self.timestamp)
        self.assertEqual(0, missing)
        self.assertEqual(1, len(batches))
        self.assertFalse(batches[0]["complete"])
        self.assertIn(":bucket:", batches[0]["scope"])
        with patch("personal_context.mail_collect.subprocess.run", return_value=CompletedProcess(
                [], 0, json.dumps({"success": True, "engine": "sqlite", "messages": [summary]}), "")):
            with self.assertRaisesRegex(ValueError, "limit"):
                recent_mailbox(self.mailbox, "2026-09-28T00:00:00Z", self.timestamp, limit=1)

    def test_empty_recent_mailbox_refreshes_scan_time_without_deleting_mail(self):
        from subprocess import CompletedProcess
        with patch("personal_context.mail_collect.subprocess.run", return_value=CompletedProcess(
                [], 0, json.dumps({"success": True, "engine": "sqlite", "messages": []}), "")):
            batches, missing = recent_mailbox(self.mailbox, "2026-09-28T00:00:00Z",
                                              "2026-10-02T12:00:00Z")
        self.assertEqual(0, missing)
        self.assertEqual(1, len(batches))
        self.assertFalse(batches[0]["complete"])
        self.assertEqual([], batches[0]["records"])
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "synthetic.sqlite3")
            try:
                first, _ = parse_export(self.lines(), self.mailbox, self.timestamp)
                for batch in first:
                    store.ingest(batch)
                original = [record for batch in first for record in batch["records"]]
                before_versions = {record["id"]: store.version_count("mail", record["id"])
                                   for record in original}
                store.ingest(batches[0])
                self.assertEqual("2026-10-02T12:00:00Z", store.last_sync("mail"))
                for record in original:
                    self.assertIsNotNone(store.get("mail", record["id"]))
                    self.assertEqual(before_versions[record["id"]],
                                     store.version_count("mail", record["id"]))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
