"""Strict SSH dispatcher. Never automatically retry an uncertain native write."""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from . import apple_write_queue as queue
from .mail_send import TARGET

COMMAND = re.compile(r'/[A-Za-z0-9_./-]+\Z')


def transport_config(target=None, remote_command=None):
    target = target or os.environ.get('PERSONAL_CONTEXT_APPLE_WRITE_TARGET', '')
    remote_command = remote_command or os.environ.get('PERSONAL_CONTEXT_APPLE_WRITE_REMOTE_COMMAND', '')
    if not TARGET.fullmatch(target) or not COMMAND.fullmatch(remote_command):
        raise ValueError('fixed SSH target and absolute receiver executable required')
    return target, remote_command


def _ssh(args, *, input, timeout, output_limit=16384):
    # Limit captured output without retaining arbitrary SSH diagnostics or item text.
    with tempfile.TemporaryFile(mode='w+') as output:
        result = subprocess.run(args,input=input,text=True,stdout=output,
                                stderr=subprocess.DEVNULL,timeout=timeout)
        output.seek(0)
        result.stdout = output.read(output_limit + 1)
        return result


def _decode(result, limit=16384):
    if result.returncode or len(result.stdout)>limit: raise ValueError('invalid receiver response')
    value = json.loads(result.stdout)
    if not isinstance(value,dict): raise ValueError('invalid receiver response')
    return value


def _receipt(raw, job_id):
    if raw.get('job_id') != job_id: raise ValueError('mismatched receipt')
    state = raw.get('state')
    if state == 'completed':
        keys={'job_id','state','item_id','completed_at','late','alert_at','alert_late','warnings'}
        if set(raw) != keys: raise ValueError('invalid completed receipt')
        item = raw['item_id']
        if not isinstance(item,str) or not 1<=len(item)<=2048 or any(ord(c)<32 for c in item): raise ValueError('invalid native ID')
        queue.timestamp(raw['completed_at'])
        if raw['alert_at']: queue.timestamp(raw['alert_at'])
        if type(raw['late']) is not bool or type(raw['alert_late']) is not bool or raw['warnings'] not in ([],['earlier_alarm_display']):
            raise ValueError('invalid completion metadata')
        return raw
    if state not in ('failed','needs_review') or set(raw) != {'job_id','state','error_code'} or raw['error_code'] not in queue.ERRORS:
        raise ValueError('invalid failure receipt')
    return raw


def read_native(kind, fields, *, ssh_runner=None):
    """Fixed read-only receiver endpoint; unavailable Mac does not enqueue a read."""
    target, command = transport_config()
    args = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=5', '-o', 'ConnectionAttempts=1', target, command, '--read-stdin']
    try:
        kwargs = dict(input=json.dumps({'kind': kind, 'fields': fields}), timeout=65)
        raw = ssh_runner(args, **kwargs) if ssh_runner else _ssh(args, **kwargs, output_limit=1024*1024)
        result = _decode(raw, limit=1024*1024)
        if result.get('success') is True: return result
        return {'success': False, 'error_code': result.get('error_code') if result.get('error_code') in queue.ERRORS else 'receiver_unavailable'}
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return {'success': False, 'error_code': 'receiver_unavailable'}


def process_queued(*, target=None, remote_command=None, queue_options=None, ssh_runner=None):
    target, command = transport_config(target,remote_command)
    options = queue_options or {}
    path, _ = queue.queue_config(**options)
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd = os.open(path.with_suffix('.worker.lock'),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    runner = ssh_runner or _ssh
    args = ['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
            '-o','ConnectTimeout=5','-o','ConnectionAttempts=1',target,command]
    with os.fdopen(fd,'a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return []
        queue.recover_interrupted(**options)
        try:
            if _decode(runner(args+['--health'],input='',timeout=15)).get('ready') is not True: return []
        except (OSError, ValueError, TypeError, subprocess.SubprocessError): return []
        results = []
        # Claim just before each delivery. A crash never strands unsent batches.
        for _ in range(10):
            jobs = queue.claim_jobs(**options,limit=1)
            if not jobs: break
            job = jobs[0]
            try:
                receipt = _receipt(_decode(runner(args+['--apply-stdin'],input=json.dumps(job),timeout=120)),job['job_id'])
                result = queue.finish_job(job['job_id'],receipt['state'],receipt.get('error_code'),receipt=receipt,**options)
            except (OSError, ValueError, TypeError, subprocess.SubprocessError):
                result = queue.finish_job(job['job_id'],'needs_review','delivery_unconfirmed',**options)
            results.append(result)
        return results


def main():
    process_queued()


if __name__ == '__main__': main()
