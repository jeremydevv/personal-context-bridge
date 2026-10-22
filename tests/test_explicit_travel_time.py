"""Explicit travel duration never needs a location fix or a route request."""
from pathlib import Path
import tempfile
import unittest

from personal_context import apple_write_queue as queue


class ExplicitTravelTimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        key = root / 'key'
        key.write_bytes(b'x' * 32)
        key.chmod(0o600)
        self.options = dict(db_path=root / 'queue', key_file=key)
        self.patch = dict(operation='update', item_id='fictional-event',
                          occurrence_start_at='2031-11-02T17:00:00Z',
                          expected_revision='a' * 64, scope='this',
                          changes={'travel_seconds': 2400})

    def test_exact_duration_is_queued_once_without_route_metadata(self):
        first = queue.queue_job('calendar', 'duration', self.patch, **self.options)
        again = queue.queue_job('calendar', 'duration', self.patch, **self.options)
        self.assertEqual(first['job_id'], again['job_id'])
        claimed = queue.claim_jobs(**self.options)
        self.assertEqual(1, len(claimed))
        self.assertEqual(self.patch, claimed[0]['fields'])

    def test_clear_and_maximum_are_valid(self):
        for seconds in [0, 60, 604800]:
            self.assertEqual(seconds, queue.validate_payload('calendar',
                self.patch | {'changes': {'travel_seconds': seconds}})['changes']['travel_seconds'])

    def test_invalid_or_mixed_duration_never_enters_queue(self):
        for seconds in [True, False, -60, 1, 2400.0, '2400', None, 604860]:
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                queue.queue_job('calendar', 'bad', self.patch | {
                    'changes': {'travel_seconds': seconds}}, **self.options)
        for extra in [{'notes': 'Unexpected'}, {'driving': None}, {'recurrence': None}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                queue.validate_payload('calendar', self.patch | {
                    'changes': {'travel_seconds': 2400, **extra}})
        with self.assertRaises(ValueError):
            queue.validate_payload('calendar', self.patch | {'scope': 'future'})
        self.assertEqual({'pending': []}, queue.pending_jobs(**self.options))

    def test_duration_cannot_be_used_for_creation_or_reminders(self):
        with self.assertRaises(ValueError):
            queue.validate_payload('calendar', dict(title='Fictional',
                start_at='2031-11-02T17:00:00Z', end_at='2031-11-02T18:00:00Z', travel_seconds=2400))
        with self.assertRaises(ValueError):
            queue.validate_payload('reminder', dict(operation='update', item_id='fictional',
                expected_revision='a' * 64, changes={'travel_seconds': 2400}))
