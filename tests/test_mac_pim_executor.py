import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from personal_context import mac_pim_executor as m

class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name)/'receipts.db'
        self.job = {'job_id':'a'*32,'kind':'calendar','fields':{'title':'$(touch /tmp/nope); --help','start_at':'2026-11-01T12:00:00-05:00','end_at':'2026-11-01T13:00:00-05:00'}}
        self.calls=[]

    def runner(self, args, **kwargs):
        self.calls.append(args)
        action = args[1]
        if action == 'auth-status': result={'authorization':'authorized'}
        elif action == 'config' and args[2] == 'show': result={'success':True, 'config':{'calendars':{'mode':'all'},'reminders':{'mode':'all'}}}
        elif action == 'config': result={'success':True,'defaultCalendar':'Existing','defaultReminderList':'Existing','availableCalendars':[{'id':'dest','title':'Existing','allowsModifications':True}],'availableReminderLists':[{'id':'dest','title':'Existing','allowsModifications':True}]}
        else: result={'success':True,'event':{'id':'native-id'},'reminder':{'id':'native-id'}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(result))

    def apply(self, **kwargs): return m.apply_job(self.job, receipt_db_path=self.db, runner=kwargs.get('runner', self.runner))

    def test_executor_rejects_oversized_or_malformed_stdin(self):
        for data in ('x'*m.MAX_INPUT, '{', '[]', '{"job_id":1,"job_id":2}'):
            with self.assertRaises(ValueError): m.read_job(io.StringIO(data))

    def test_executor_accepts_bounded_inline_attachment_above_old_input_limit(self):
        import base64
        import hashlib
        data = b'\x89PNG\r\n\x1a\n' + b'fictional' * 25000
        fields = dict(operation='update_private', item_id='native-id', expected_revision='a'*64,
                      occurrence_start_at='2031-11-01T17:00:00Z', scope='this',
                      changes={'add_attachments':[dict(filename='fictional.png', media_type='image/png',
                          content_base64=base64.b64encode(data).decode(), sha256=hashlib.sha256(data).hexdigest())]})
        job = dict(job_id='a'*32, kind='calendar', fields=fields)
        self.assertGreater(len(json.dumps(job)), 160000)
        self.assertEqual(m.read_job(io.StringIO(json.dumps(job))), job)

    def test_executor_passes_metacharacters_as_literal_argv_values(self):
        self.job['fields']['calendar']='Existing'
        self.assertEqual(self.apply()['state'],'completed')
        create=next(c for c in self.calls if c[1]=='create')
        self.assertIn('--title='+self.job['fields']['title'],create)
        self.assertIn('--calendar=dest',create)

    def test_completed_receipt_replay_does_not_create_again(self):
        first=self.apply(); second=self.apply()
        self.assertEqual(first, second)
        self.assertEqual(len([c for c in self.calls if c[1]=='create']),1)

    def test_interrupted_apply_returns_needs_review(self):
        def crash(args, **kwargs):
            if args[1]=='create': raise KeyboardInterrupt()
            return self.runner(args, **kwargs)
        with self.assertRaises(KeyboardInterrupt): self.apply(runner=crash)
        self.assertEqual(self.apply()['state'],'needs_review')
        self.assertFalse(any(c[1]=='create' for c in self.calls))

    def test_cli_failure_is_sanitized(self):
        def fail(args, **kwargs):
            if args[1]=='create': return SimpleNamespace(returncode=1, stdout='private notes')
            return self.runner(args, **kwargs)
        result=self.apply(runner=fail)
        self.assertEqual(result['state'],'needs_review')
        self.assertNotIn('private notes',str(result))

    def test_ambiguous_destination_fails_before_create(self):
        self.job['fields']['calendar']='Existing'
        def ambiguous(args, **kwargs):
            out=self.runner(args,**kwargs)
            if args[1:]==['config','init','--format=json']:
                obj=json.loads(out.stdout); obj['availableCalendars'] *= 2; out.stdout=json.dumps(obj)
            return out
        self.assertEqual(self.apply(runner=ambiguous)['state'],'failed')
        self.assertFalse(any(c[1]=='create' for c in self.calls))

    def test_early_reminder_alert_reports_lateness_and_display_time(self):
        self.job['kind']='reminder'; self.job['fields']={'title':'Example','due_at':'2020-01-01T12:00:00-05:00','alarm_minutes_before':15}
        receipt=self.apply()
        self.assertTrue(receipt['late'])
        self.assertEqual(receipt['alert_at'],'2020-01-01T11:45:00-05:00')
        self.assertIn('earlier_alarm_display',receipt['warnings'])

    def test_configured_default_uses_native_snake_case_key(self):
        def configured(args, **kwargs):
            result=self.runner(args, **kwargs)
            obj=json.loads(result.stdout)
            if args[1:3]==['config','show']: obj['config']['default_calendar']='Configured'
            if args[1:3]==['config','init']: obj['availableCalendars'].append({'id':'configured-id','title':'Configured','allowsModifications':True})
            result.stdout=json.dumps(obj); return result
        self.assertEqual(self.apply(runner=configured)['state'],'completed')
        create=next(c for c in self.calls if c[1]=='create')
        self.assertIn('--calendar=configured-id',create)

    def test_authorized_app_helper_receives_literal_arguments(self):
        from unittest.mock import patch
        def helper_runner(args, **kwargs):
            self.assertEqual(args[:3],['/usr/bin/open','-n','-W'])
            self.assertEqual(args[5],'--args')
            cli, out_path, err_path = args[6:9]
            result=self.runner([cli]+args[9:],**kwargs)
            Path(out_path).write_text(result.stdout)
            return SimpleNamespace(returncode=0,stdout='')
        with patch.dict('os.environ',{'PERSONAL_CONTEXT_APPLE_PIM_HELPER':'/Applications/Example.app'}):
            result=self.apply(runner=helper_runner)
        self.assertEqual(result['state'],'completed')

    def test_system_default_with_duplicate_names_is_resolved_by_eventkit(self):
        def duplicate(args, **kwargs):
            result=self.runner(args, **kwargs)
            if args[1:3]==['config','init']:
                obj=json.loads(result.stdout);obj['availableCalendars']*=2;result.stdout=json.dumps(obj)
            return result
        self.assertEqual(self.apply(runner=duplicate)['state'],'completed')
        create=next(c for c in self.calls if c[1]=='create')
        self.assertFalse(any(c.startswith('--calendar=') for c in create))

    def test_repeated_dst_hour_is_rejected_before_native_create(self):
        from unittest.mock import patch
        from zoneinfo import ZoneInfo
        self.job['kind']='reminder';self.job['fields']={'title':'Example','due_at':'2026-11-01T01:30:00-05:00'}
        with patch.object(m,'_local_zone',return_value=ZoneInfo('America/New_York'),create=True):
            result=self.apply()
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['error_code'],'unsupported_reminder_time')
        self.assertFalse(any(c[1]=='create' for c in self.calls))

    def test_app_wait_race_accepts_only_native_success_protocol(self):
        from unittest.mock import patch
        def helper_runner(args, **kwargs):
            cli,out_path,err_path=args[6:9]
            native=self.runner([cli]+args[9:],**kwargs)
            Path(out_path).write_text(native.stdout)
            return SimpleNamespace(returncode=1,stdout='',stderr='Unable to block on applications (initial call to kevent() failed: No such process)')
        with patch.dict('os.environ',{'PERSONAL_CONTEXT_APPLE_PIM_HELPER':'/Applications/Example.app'}):
            result=self.apply(runner=helper_runner)
        self.assertEqual(result['state'],'completed')

    def test_app_wait_failure_without_native_output_cannot_complete(self):
        from unittest.mock import patch
        with patch.dict('os.environ',{'PERSONAL_CONTEXT_APPLE_PIM_HELPER':'/Applications/Example.app'}):
            result=self.apply(runner=lambda *a,**kw: SimpleNamespace(returncode=1,stdout=''))
        self.assertEqual(result['state'],'failed')
