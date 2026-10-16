import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from personal_context import apple_write_queue as q
from personal_context import mac_pim_executor as executor


class EditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        key = root / 'key'
        key.write_bytes(b'x' * 32)
        key.chmod(0o600)
        self.options = dict(db_path=root / 'queue', key_file=key)
        self.receipts = root / 'receipts'
        self.fields = dict(operation='update', item_id='native-event',
                           occurrence_start_at='2026-11-02T12:00:00-05:00',
                           expected_revision='a' * 64, scope='this',
                           changes={'location': 'New place', 'notes': ''})

    def test_patch_queue_preserves_absent_fields_and_explicit_clear(self):
        try:
            result = q.queue_job('calendar', 'patch', self.fields, **self.options)
        except ValueError as exc:
            self.fail('Structured updates are not accepted: ' + str(exc))
        self.assertEqual(result['state'], 'queued')
        fields = q.claim_jobs(**self.options)[0]['fields']
        self.assertEqual(fields['changes'], {'location': 'New place', 'notes': ''})
        self.assertNotIn('title', fields['changes'])

    def test_delete_requires_revision_and_exact_occurrence(self):
        valid = self.fields | {'operation': 'delete'}
        valid.pop('changes')
        try:
            q.queue_job('calendar', 'delete', valid, **self.options)
        except ValueError as exc:
            self.fail('Native deletes are not accepted: ' + str(exc))
        for key in ('expected_revision', 'occurrence_start_at', 'item_id'):
            invalid = valid.copy()
            invalid.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                q.queue_job('calendar', 'missing-' + key, invalid, **self.options)

    def test_unsupported_features_are_rejected_before_queueing(self):
        for changes in ({'urgent': True}, {'parent_id': 'parent'}, {'travel_time': 'automatic'},
                        {'alarm_minutes_before': True}, {'alerts': [True]},
                        {'calendar': ''}, {'completed': True}, {}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                q.queue_job('calendar', 'invalid', self.fields | {'changes': changes}, **self.options)
        self.assertEqual(q.pending_jobs(**self.options), {'pending': []})

    def test_extended_create_fields_and_reminder_completion(self):
        try:
            event = q.validate_payload('calendar', dict(title='Example',
                start_at='2026-11-02T12:00:00-05:00', end_at='2026-11-02T13:00:00-05:00',
                location='Library', alerts=[0, 30], all_day=False, timezone='America/New_York',
                recurrence={'frequency': 'weekly', 'interval': 2, 'count': 4}))
            reminder = q.validate_payload('reminder', dict(operation='update', item_id='reminder',
                expected_revision='b' * 64, changes={'completed': True, 'priority': 1, 'due_at': ''}))
        except ValueError as exc:
            self.fail('Extended fields are not accepted: ' + str(exc))
        self.assertEqual(event['alerts'], [0, 30])
        self.assertEqual(q.validate_payload('calendar', event), event)
        created_reminder = q.validate_payload('reminder', dict(title='Example', due_at='2031-11-04T17:00:00Z', alerts=[]))
        self.assertEqual(q.validate_payload('reminder', created_reminder), created_reminder)
        self.assertEqual(reminder['changes']['completed'], True)

    def test_native_patch_uses_private_request_file_and_sanitized_receipt(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            self.assertEqual(args[1], 'bridge')
            request_path = Path(args[2].removeprefix('--request='))
            self.assertEqual(request_path.stat().st_mode & 0o777, 0o600)
            request = json.loads(request_path.read_text())
            self.assertEqual(request['fields']['changes'], {'location': 'New place', 'notes': ''})
            return SimpleNamespace(returncode=0, stdout=json.dumps({
                'success': True, 'verified': True, 'item_id': 'native-event',
                'revision': 'b' * 64, 'private': 'never put this in receipts'}))
        job = dict(job_id='c' * 32, kind='calendar', fields=self.fields)
        try:
            result = executor.apply_job(job, receipt_db_path=self.receipts, runner=runner)
        except ValueError as exc:
            self.fail('Native patch adapter is missing: ' + str(exc))
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['item_id'], 'native-event')
        self.assertNotIn('private', str(result))
        self.assertEqual(executor.apply_job(job, receipt_db_path=self.receipts, runner=runner), result)
        self.assertEqual(len(calls), 1)
        self.assertFalse(Path(calls[0][2].removeprefix('--request=')).exists())

    def test_native_revision_conflict_is_definite_failure(self):
        job = dict(job_id='d' * 32, kind='calendar', fields=self.fields)
        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout=json.dumps({
                'success': False, 'error_code': 'revision_conflict', 'write_started': False}))
        try:
            result = executor.apply_job(job, receipt_db_path=self.receipts, runner=runner)
        except ValueError as exc:
            self.fail('Native patch adapter is missing: ' + str(exc))
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error_code'], 'revision_conflict')

    def test_private_reminder_changes_are_explicit_and_cannot_mix_public_fields(self):
        fields = dict(operation='update_private', item_id='reminder', expected_revision='b' * 64,
                      changes={'urgent': True, 'add_subtasks': [{'title': 'Bring notes', 'notes': 'Chapter 1'}]})
        try:
            job = q.queue_job('reminder', 'private', fields, **self.options)
        except ValueError as exc:
            self.fail('Private ReminderKit operations are not accepted: ' + str(exc))
        self.assertEqual(job['state'], 'queued')
        for changes in ({'urgent': True, 'notes': 'mixed'}, {'urgent': 1}, {'add_subtasks': []},
                        {'add_subtasks': [{'title': ''}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                q.queue_job('reminder', 'invalid', fields | {'changes': changes}, **self.options)

    def test_automatic_route_retries_keep_original_job_and_reject_changed_intent(self):
        event = dict(title='Example', start_at='2031-11-02T17:00:00Z', end_at='2031-11-02T18:00:00Z', location='Library')
        driving = dict(seconds=600, computed_at='2026-10-16T20:00:00Z', origin_observed_at='2026-10-16T20:00:00Z',
                       latitude=37.3, longitude=-122.0, destination='Library')
        try:
            first = q.queue_job('calendar', 'route', event | {'driving': driving}, automatic_identity=True, **self.options)
            retry = q.existing_job('calendar', 'route', event, automatic_identity=True, **self.options)
        except (TypeError, AttributeError) as exc:
            self.fail('Automatic route retry identity is missing: ' + str(exc))
        self.assertEqual(first, retry)
        second = q.queue_job('calendar', 'route', event | {'driving': driving | {'seconds': 700}}, automatic_identity=True, **self.options)
        self.assertEqual(first, second)
        with self.assertRaises(ValueError):
            q.existing_job('calendar', 'route', event | {'title': 'Changed'}, automatic_identity=True, **self.options)
