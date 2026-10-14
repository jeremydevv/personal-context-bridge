import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from personal_context.spool import Spool


class SpoolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.spool = Spool(Path(self.temp.name) / "spool")

    def tearDown(self):
        self.temp.cleanup()

    def test_failed_delivery_keeps_private_batch_for_retry(self):
        batch = {"schema": 1, "records": [{"id": "one"}]}
        self.spool.enqueue([batch])
        with self.assertRaises(RuntimeError):
            self.spool.flush(lambda payload: (_ for _ in ()).throw(RuntimeError("offline")))
        queued = self.spool.pending()
        self.assertEqual(1, len(queued))
        self.assertEqual(0o600, queued[0].stat().st_mode & 0o777)
        self.assertEqual(batch, json.loads(queued[0].read_text()))

    def test_successful_delivery_removes_batch(self):
        self.spool.enqueue([{"schema": 1, "records": []}])
        delivered = []
        self.assertEqual(1, self.spool.flush(delivered.append))
        self.assertEqual([], self.spool.pending())
        self.assertEqual(1, len(delivered))

    def test_many_batches_are_one_retryable_transfer(self):
        self.spool.enqueue([{"scope": "one"}, {"scope": "two"}])
        self.assertEqual(1, len(self.spool.pending()))
        envelope = json.loads(self.spool.pending()[0].read_text())
        self.assertEqual(["one", "two"], [item["scope"] for item in envelope["batches"]])

    def test_queue_stays_fifo_when_wall_clock_moves_back(self):
        with patch("personal_context.spool.time.time_ns", side_effect=[100, 99]):
            self.spool.enqueue([{"scope": "first"}])
            self.spool.enqueue([{"scope": "second"}])
        scopes = [json.loads(path.read_text())["scope"] for path in self.spool.pending()]
        self.assertEqual(["first", "second"], scopes)


if __name__ == "__main__":
    unittest.main()
