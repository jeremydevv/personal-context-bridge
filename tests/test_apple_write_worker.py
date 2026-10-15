import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from test_apple_write_queue import QueueTests, EVENT
from personal_context import apple_write_queue as q
from personal_context import apple_write_worker as w

class WorkerTests(QueueTests):
    def process(self, runner):
        return w.process_queued(target='user@mac.example', remote_command='/private/bin/apple-receiver', queue_options=self.opts, ssh_runner=runner)

    def runner(self,args,**kwargs):
        if args[-1]=='--health': result={'ready':True}
        else:
            job=json.loads(kwargs['input'])
            result={'job_id':job['job_id'],'state':'completed','item_id':'native-id','completed_at':'2026-11-01T12:00:00-05:00','late':False,'alert_at':'','alert_late':False,'warnings':[]}
        return SimpleNamespace(returncode=0,stdout=json.dumps(result))

    def test_offline_preflight_keeps_job_queued(self):
        job=self.queue()
        self.process(lambda *a,**kw: SimpleNamespace(returncode=255,stdout=''))
        self.assertEqual(q.job_status(job['job_id'],**self.opts)['state'],'queued')

    def test_worker_sends_json_only_on_stdin(self):
        self.queue(title='$(private text)')
        calls=[]
        def runner(args,**kwargs):
            calls.append((args,kwargs)); return self.runner(args,**kwargs)
        result=self.process(runner)
        self.assertEqual(result[0]['state'],'completed')
        self.assertNotIn('private text',str([a for a,kw in calls]))
        self.assertIn('private text',calls[-1][1]['input'])
        self.assertIn('StrictHostKeyChecking=yes',calls[-1][0])

    def test_invalid_receipt_marks_needs_review(self):
        self.queue()
        def runner(args,**kwargs):
            return self.runner(args,**kwargs) if args[-1]=='--health' else SimpleNamespace(returncode=0,stdout='{"job_id":"wrong","state":"completed"}')
        self.assertEqual(self.process(runner)[0]['state'],'needs_review')

    def test_post_send_timeout_is_not_retried(self):
        self.queue()
        def runner(args,**kwargs):
            if args[-1]!='--health': raise subprocess.TimeoutExpired(args,60)
            return self.runner(args,**kwargs)
        self.assertEqual(self.process(runner)[0]['state'],'needs_review')
        self.assertEqual(self.process(self.runner),[])

    def test_only_one_worker_claims_a_job(self):
        self.queue()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _: q.claim_jobs(**self.opts),range(2)))
        self.assertEqual(sum(map(len,results)),1)

    def test_crashed_worker_is_never_retried(self):
        job=self.queue(); q.claim_jobs(**self.opts)
        self.process(self.runner)
        self.assertEqual(q.job_status(job['job_id'],**self.opts)['state'],'needs_review')

    def test_remote_command_cannot_include_shell_code(self):
        with self.assertRaises(ValueError):
            w.process_queued(target='user@mac',remote_command='/bin/true; echo unsafe',queue_options=self.opts)
