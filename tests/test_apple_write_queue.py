import tempfile
import unittest
from pathlib import Path
from personal_context import apple_write_queue as q

EVENT = dict(title='Example', start_at='2026-11-01T12:00:00-05:00', end_at='2026-11-01T13:00:00-05:00', notes='private notes')

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        key = self.root/'key'; key.write_bytes(b'x'*32); key.chmod(0o600)
        self.opts = dict(db_path=self.root/'outbox.db', key_file=key)

    def queue(self, **fields):
        return q.queue_job('calendar', 'example-request', EVENT | fields, **self.opts)

    def test_queue_requires_private_key(self):
        self.opts['key_file'].chmod(0o644)
        with self.assertRaises(RuntimeError): self.queue()

    def test_queue_rejects_naive_datetime(self):
        with self.assertRaises(ValueError): self.queue(start_at='2026-11-01T12:00:00')

    def test_same_request_key_same_payload_returns_existing_job(self):
        first = self.queue()
        self.assertEqual(first, self.queue())
        self.assertNotIn(b'private notes', self.opts['db_path'].read_bytes())

    def test_same_request_key_changed_payload_conflicts(self):
        self.queue()
        with self.assertRaises(ValueError): self.queue(title='Changed')

    def test_cancel_after_claim_fails(self):
        job = self.queue(); q.claim_jobs(**self.opts)
        self.assertEqual(q.cancel_job(job['job_id'], **self.opts)['state'], 'delivering')

    def test_status_omits_notes(self):
        job = self.queue()
        self.assertNotIn('private notes', str(q.job_status(job['job_id'], **self.opts)))
        self.assertNotIn('private notes', str(q.pending_jobs(**self.opts)))

    def test_cancelled_job_cannot_be_claimed(self):
        job = self.queue(); q.cancel_job(job['job_id'], **self.opts)
        self.assertEqual(q.claim_jobs(**self.opts), [])

    def test_validation(self):
        for fields in ({'end_at': EVENT['start_at']}, {'alarm_minutes_before': True}, {'title': ''}, {'extra': 'x'}):
            with self.assertRaises(ValueError): self.queue(**fields)
        with self.assertRaises(ValueError): q.queue_job('reminder', 'r', {'title':'Example', 'alarm_minutes_before':15}, **self.opts)

    def test_reminder_rejects_unrepresentable_seconds(self):
        with self.assertRaises(ValueError):
            q.queue_job('reminder','seconds',{'title':'Example','due_at':'2026-11-01T12:00:30-05:00'},**self.opts)
