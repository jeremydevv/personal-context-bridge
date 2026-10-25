"""Private metadata-only inbox for GUI launchd's existing read permissions.

SSH accepts fixed source jobs; only the configured LaunchAgent executes them.
Supervisor acceptance never serves as an archive-completion receipt.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import threading
import subprocess
import tempfile
import time

LABEL='org.personalcontext.personal-context-refresh-inbox'
SOURCES=('calendar','reminder','contact','mail','message','note','voice_memo','canvas')


def _private(path):
    path=Path(path)
    info=path.lstat()
    if path.is_symlink() or info.st_uid!=os.getuid() or info.st_mode & 0o077:
        raise ValueError('private inbox path required')
    return path


def _config(path):
    path=_private(path or Path(os.environ.get('PERSONAL_CONTEXT_CONFIG_DIR',Path.home()/'.config/personal-context-bridge'))/'config.json')
    if not path.is_file():raise ValueError('private config file required')
    return path,hashlib.sha256(path.read_bytes()).hexdigest()


def _root():
    path=Path(os.environ.get('PERSONAL_CONTEXT_DATA_DIR',Path.home()/'.local/share/personal-context-bridge'))/'refresh-inbox'
    if path.is_symlink():raise ValueError('private inbox required')
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    return _private(path)


def _read(path):
    path=_private(path)
    if not path.is_file() or path.stat().st_size>131072:raise ValueError('invalid inbox metadata')
    value=json.loads(path.read_text())
    if not isinstance(value,dict):raise ValueError('invalid inbox metadata')
    return value


def _write(path,value):
    raw=json.dumps(value,separators=(',',':'),allow_nan=False).encode()
    if len(raw)>131072:raise ValueError('inbox result limit')
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.pending-')
    temp=Path(name)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
        directory=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:temp.unlink(missing_ok=True)


def _validate(job):
    if (not isinstance(job,dict) or set(job)!={'refresh_id','attempt_id','source','mode','config_digest'}
            or job['source'] not in SOURCES or job['mode'] not in ('recent','full')
            or any(not isinstance(job[k],str) or not re.fullmatch('[a-f0-9]{32}',job[k]) for k in ('refresh_id','attempt_id'))
            or not isinstance(job['config_digest'],str) or not re.fullmatch('[a-f0-9]{64}',job['config_digest'])):
        raise ValueError('invalid inbox job')
    return job


def _result(job,value):
    """Persist only the refresh contract, never arbitrary collector output."""
    if not isinstance(value,dict):raise ValueError('invalid inbox result')
    for field in ('refresh_id','attempt_id','source'):
        if field in value and value[field]!=job[field]:raise ValueError('inbox result identity mismatch')
    allowed=('collection_finished','coverage','error_code','retryable','phase','batch_ids','acked_batch_ids',
             'archive_verified','headless','headless_mode','gui_fallback','local_replica_only',
             'upstream_freshness','completion_kind','attachment_processing','app_lifecycle')
    result={name:value[name] for name in allowed if name in value}
    result.update({name:job[name] for name in ('refresh_id','attempt_id','source')})
    return {'job':job,'result':result}


def _cached(root,job):
    path=root/(job['attempt_id']+'.result.json')
    if not path.exists():return None
    saved=_read(path)
    if saved.get('job')!=job:raise ValueError('inbox result identity mismatch')
    return _result(job,saved.get('result'))['result']


def kickstart():
    try:
        result=subprocess.run(['launchctl','kickstart','gui/'+str(os.getuid())+'/'+LABEL],capture_output=True,timeout=15)
        return result.returncode==0
    except (OSError,subprocess.TimeoutExpired):return False


def enqueue(source,refresh_id,attempt_id,mode='recent',config_path=None,wait_seconds=3600):
    from .refresh_worker import resource_lock
    config,digest=_config(config_path)
    job=_validate(dict(source=source,refresh_id=refresh_id,attempt_id=attempt_id,mode=mode,config_digest=digest))
    if not isinstance(wait_seconds,(int,float)) or not 0<=wait_seconds<=3600:raise ValueError('invalid inbox wait')
    root=_root();path=root/(attempt_id+'.job.json')
    with resource_lock(root/'enqueue.lock'):
        if path.exists():
            if _read(path)!=job:raise ValueError('inbox attempt identity reused')
        else:_write(path,job)
        cached=_cached(root,job)
        if cached is not None:return cached
    if not kickstart():
        value={'retryable':True,'phase':'waiting_for_gui_worker','error_code':'gui_worker_unavailable'}
        _write(root/(attempt_id+'.result.json'),_result(job,value))
        return _cached(root,job)
    deadline=time.monotonic()+wait_seconds
    while True:
        cached=_cached(root,job)
        if cached is not None:return cached
        if time.monotonic()>=deadline:
            return dict(_result(job,{'retryable':True,'phase':'waiting_for_gui_worker','error_code':'gui_worker_pending'})['result'])
        time.sleep(min(.25,max(0,deadline-time.monotonic())))


def drain(config_path=None):
    from .refresh_worker import resource_lock,run_mac,error_code
    config,digest=_config(config_path);root=_root();processed=0
    try:
        with resource_lock(root/'drain.lock',wait=0):
            for path in sorted(root.glob('*.job.json')):
                job=_validate(_read(path))
                if path.name!=job['attempt_id']+'.job.json':raise ValueError('inbox filename mismatch')
                if _cached(root,job) is not None:continue
                started=root/(job['attempt_id']+'.started.json')
                if job['config_digest']!=digest:
                    result={'collection_finished':False,'coverage':'unknown','error_code':'configuration_changed'}
                elif started.exists():
                    if _read(started)!=job:raise ValueError('inbox start identity mismatch')
                    result={'retryable':True,'phase':'interrupted','error_code':'collector_interrupted'}
                else:
                    _write(started,job)
                    previous=None
                    if threading.current_thread() is threading.main_thread():
                        def time_limit(signum,frame):raise RuntimeError('collector_time_limit')
                        previous=signal.signal(signal.SIGALRM,time_limit);signal.alarm(3600)
                    try:result=run_mac(job['source'],job['refresh_id'],job['attempt_id'],mode=job['mode'],config_path=config)
                    except (OSError,RuntimeError,ValueError,ImportError) as exc:
                        result={'collection_finished':False,'coverage':'unknown','error_code':error_code(exc)}
                        if result['error_code']=='collection_busy':result.update(retryable=True,phase='waiting_for_resource')
                    finally:
                        if previous is not None:signal.alarm(0);signal.signal(signal.SIGALRM,previous)
                _write(root/(job['attempt_id']+'.result.json'),_result(job,result));processed+=1
    except RuntimeError as exc:
        if str(exc)=='collection_busy':return {'processed':0,'already_running':True}
        raise
    return {'processed':processed}
