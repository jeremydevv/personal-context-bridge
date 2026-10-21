"""End-only recurrence contract; storage is fictional and private temporary files only."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from personal_context import apple_write_queue as q, mac_pim_executor as executor


class RecurrenceEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        key = root / 'key'
        key.write_bytes(b'x' * 32)
        key.chmod(0o600)
        self.options = dict(db_path=root / 'outbox', key_file=key)
        self.receipts = root / 'receipts'
        self.patch = {'recurrence_end': {'date': '2027-05-28', 'timezone': 'America/New_York'}}
        self.fields = dict(operation='update', item_id='fictional-series',
                           occurrence_start_at='2026-10-20T08:00:00-04:00',
                           expected_revision='a' * 64, scope='future', changes=self.patch)

    def test_accepts_end_only_without_replacing_existing_rule(self):
        self.assertEqual(q.validate_payload('calendar', self.fields), self.fields)
        job = q.queue_job('calendar', 'end-only', self.fields, **self.options)
        self.assertEqual(q.queue_job('calendar', 'end-only', self.fields, **self.options)['job_id'], job['job_id'])
        claimed = q.claim_jobs(**self.options)
        self.assertEqual(claimed[0]['fields']['changes'], self.patch)
        self.assertNotIn('recurrence', claimed[0]['fields']['changes'])
        with self.assertRaises(ValueError):
            q.queue_job('calendar', 'end-only', self.fields | {'changes': {'recurrence_end': {'date': '2027-05-27', 'timezone': 'America/New_York'}}}, **self.options)

    def test_invalid_end_inputs_never_queue(self):
        for value in (None, {}, {'date':'2027-02-30','timezone':'America/New_York'},
                      {'date':'2027-5-28','timezone':'America/New_York'},
                      {'date':'2027-05-28T00:00:00Z','timezone':'UTC'},
                      {'date':'2027-05-28','timezone':'Not/AZone'},
                      {'date':'2027-05-28','timezone':'UTC','count':4},
                      {'date':'2025-05-28','timezone':'America/New_York'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                q.queue_job('calendar', 'invalid', self.fields | {'changes': {'recurrence_end': value}}, **self.options)
        self.assertEqual(q.pending_jobs(**self.options), {'pending': []})

    def test_requires_future_scope_exact_revision_and_end_only_patch(self):
        for fields in (self.fields | {'scope':'this'}, self.fields | {'expected_revision':''},
                       self.fields | {'changes': self.patch | {'recurrence':None}},
                       self.fields | {'changes': self.patch | {'title':'Changed'}}):
            with self.assertRaises(ValueError): q.validate_payload('calendar', fields)
        with self.assertRaises(ValueError):
            q.validate_payload('calendar', dict(title='Fictional',start_at='2026-10-20T08:00:00-04:00',
                end_at='2026-10-20T09:00:00-04:00',**self.patch))
        with self.assertRaises(ValueError):
            q.validate_payload('reminder', dict(operation='update',item_id='fictional',expected_revision='a'*64,changes=self.patch))

    def test_receiver_preserves_end_only_payload_and_replays_receipt(self):
        calls = []
        def runner(args, **kwargs):
            request = json.loads(Path(args[2].removeprefix('--request=')).read_text())
            calls.append(deepcopy(request))
            self.assertEqual(request['fields'], self.fields)
            return SimpleNamespace(returncode=0, stdout=json.dumps(dict(success=True,verified=True,item_id='fictional-series')))
        job = dict(job_id='e'*32,kind='calendar',fields=self.fields)
        first = executor.apply_job(job,receipt_db_path=self.receipts,runner=runner)
        self.assertEqual(first['state'],'completed')
        self.assertEqual(executor.apply_job(job,receipt_db_path=self.receipts,runner=runner),first)
        self.assertEqual(len(calls),1)

    def test_stale_or_uncertain_native_results_are_never_retried(self):
        for error, started, state in [('revision_conflict',False,'failed'),('verification_failed',True,'needs_review')]:
            calls = []
            def runner(*args, **kwargs):
                calls.append(1)
                return SimpleNamespace(returncode=0,stdout=json.dumps(dict(success=False,error_code=error,write_started=started)))
            job = dict(job_id=('a' if not started else 'b')*32,kind='calendar',fields=self.fields)
            result = executor.apply_job(job,receipt_db_path=self.receipts,runner=runner)
            self.assertEqual(result['state'],state)
            self.assertEqual(executor.apply_job(job,receipt_db_path=self.receipts,runner=runner),result)
            self.assertEqual(len(calls),1)

    def test_notification_consent_is_explicit_and_strict(self):
        self.assertEqual(q.validate_payload('calendar', self.fields | {'allow_invitation_delivery': True})['allow_invitation_delivery'], True)
        for value in (1, 'yes', None):
            with self.assertRaises(ValueError): q.validate_payload('calendar', self.fields | {'allow_invitation_delivery': value})

    def test_weekly_creation_can_seed_exact_weekdays_without_native_bypass(self):
        fields = dict(title='Fictional series',start_at='2026-10-20T08:00:00-04:00',end_at='2026-10-20T09:00:00-04:00',
            recurrence={'frequency':'weekly','weekdays':['tuesday','wednesday','thursday','friday']})
        self.assertEqual(q.validate_payload('calendar',fields)['recurrence']['weekdays'],fields['recurrence']['weekdays'])
        for rule in ({'frequency':'daily','weekdays':['monday']}, {'frequency':'weekly','weekdays':[]},
                     {'frequency':'weekly','weekdays':['monday','monday']}, {'frequency':'weekly','weekdays':['MONDAY']}):
            with self.assertRaises(ValueError): q.validate_payload('calendar', fields | {'recurrence':rule})
