"""Bounded source-only refresh worker. Commands come only from private config."""
import argparse
import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import threading
import uuid

from .refresh_tracking import MAC_SOURCES, coordinator

ACTIONS={'calendar':'fast-sync','reminder':'fast-sync','contact':'contacts-sync','mail':'mail-fast-sync','message':'messages-sync','note':'notes-sync','voice_memo':'voice-memos-sync'}


def source_config(config,source):
    if source not in MAC_SOURCES: raise ValueError('unsupported_mac_source')
    selected=dict(config)
    selected['calendar_ids']=config.get('calendar_ids',[]) if source=='calendar' else []
    selected['reminder_ids']=config.get('reminder_ids',[]) if source=='reminder' else []
    for name,s in [('all_calendars','calendar'),('all_reminders','reminder'),('all_contacts','contact'),('all_mailboxes','mail'),('all_messages','message'),('all_notes','note'),('all_voice_memos','voice_memo')]:
        selected[name]=config.get(name,False) if source==s else False
    selected['mailbox_urls']=config.get('mailbox_urls',[]) if source=='mail' else []
    if source not in ('calendar','reminder','canvas'):
        flag={'contact':'all_contacts','message':'all_messages','note':'all_notes','voice_memo':'all_voice_memos'}.get(source)
        if flag and not selected.get(flag): raise ValueError('source_disabled')
    if source=='calendar' and not (selected['calendar_ids'] or selected['all_calendars']): raise ValueError('source_disabled')
    if source=='reminder' and not (selected['reminder_ids'] or selected['all_reminders']): raise ValueError('source_disabled')
    return selected


@contextlib.contextmanager
def resource_lock(path,wait=5):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as lock:
        deadline=time.monotonic()+wait
        while True:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); break
            except BlockingIOError:
                if time.monotonic()>=deadline: raise RuntimeError('collection_busy')
                time.sleep(.05)
        try: yield
        finally: fcntl.flock(lock,fcntl.LOCK_UN)


class AggregateOutput(io.TextIOBase):
    def __init__(self): self.size=0; self.partial=False; self.attachments=None
    def write(self,value):
        self.size+=len(value)
        if self.size>65536: raise RuntimeError('collector_output_limit')
        # Only coverage signals are retained. Source contents never enter status.
        for line in value.splitlines():
            try: obj=json.loads(line)
            except ValueError: continue
            if isinstance(obj,dict) and all(isinstance(obj.get(k),int) for k in ('available_files','pending_before_run','imported','remaining')):
                self.attachments={k:obj[k] for k in ('available_files','pending_before_run','imported','remaining')}
            if isinstance(obj,dict) and any(obj.get(k) for k in ('missing_bodies','failed','errors','unavailable','already_running','pending')): self.partial=True
        return len(value)


def run_mac(source,refresh_id,attempt_id,mode='recent',config_path=None):
    from .cli import load_config, main as collect, deliver_ssh
    from .spool import Spool
    if source not in MAC_SOURCES: raise ValueError('unsupported_mac_source')
    for value in (refresh_id,attempt_id):
        if not re.fullmatch('[a-f0-9]{32}',value): raise ValueError('invalid_refresh_identity')
    config_path=Path(config_path or Path(os.environ.get('PERSONAL_CONTEXT_CONFIG_DIR',Path.home()/'.config/personal-context-bridge'))/'config.json')
    if config_path.is_symlink() or config_path.stat().st_mode & 0o077: raise ValueError('private_config_required')
    config=load_config(config_path)
    source_config(config,source)
    adapter={'contact':'contacts','note':'notes'}.get(source)
    if adapter and config.get('headless',{}).get(adapter,{}).get('mode','legacy')=='legacy':
        return {'collection_finished':False,'coverage':'unknown','error_code':'headless_adapter_unconfigured','refresh_id':refresh_id,'attempt_id':attempt_id,'source':source}
    root=Path(os.environ.get('PERSONAL_CONTEXT_DATA_DIR',Path.home()/'.local/share/personal-context-bridge'))
    Spool.begin_tracking(refresh_id,attempt_id,source)
    env_before=dict(os.environ)
    output=AggregateOutput()
    try:
        os.environ.update(PERSONAL_CONTEXT_REFRESH_SOURCE=source,PERSONAL_CONTEXT_REFRESH_HEADLESS='1',PERSONAL_CONTEXT_SYNC_LANE='fast' if mode=='recent' else 'full')
        with resource_lock(root/'refresh-collection.lock'):
            with contextlib.redirect_stdout(output):
                if source=='canvas':
                    from .canvas_sync_runner import run
                    result=run(config_dir=config_path.parent,data_dir=root)
                    if isinstance(result,dict) and (result.get('already_running') or result.get('pending') or result.get('failed') or result.get('coverage') in ('partial','unknown')): output.partial=True
                else:
                    action=ACTIONS[source]
                    if mode=='full': action={'fast-sync':'sync','mail-fast-sync':'mail-sync'}.get(action,action)
                    result=collect([action,'--config',str(config_path)])
                    if result not in (0,None): raise RuntimeError('collection_failed')
                    if source=='message':
                        attachment_result=collect(['attachment-sync','--config',str(config_path),'--limit','50'])
                        if attachment_result not in (0,None): raise RuntimeError('attachment_collection_failed')
        if source=='canvas' and isinstance(result,dict) and result.get('already_running'):
            return {'retryable':True,'error_code':'collection_busy','phase':'waiting_for_resource','refresh_id':refresh_id,'attempt_id':attempt_id,'source':source}
        result=dict(Spool.tracking_result('partial' if output.partial else 'complete'),headless=True,gui_fallback=False,upstream_freshness='unknown')
        if source=='message':
            result['attachment_processing']={'invoked':True,'limit':50,'collection':'available_local_files','upstream_hydration':'unknown','counts':output.attachments,'completion_kind':'direct_ssh_postcommit_response'}
        if source=='mail':
            mail_mode=config.get('headless',{}).get('mail',{}).get('mode','legacy')
            result.update(headless_mode=mail_mode,upstream_freshness='unknown',local_replica_only=mail_mode=='local',headless=mail_mode!='legacy',gui_fallback=mail_mode=='legacy',app_lifecycle='guarded_existing_policy' if mail_mode=='legacy' else 'not_launched')
        if Spool.app_lifecycle is not None:
            result['app_lifecycle']=Spool.app_lifecycle
            if Spool.app_lifecycle.get('cleanup')=='failed': result['coverage']='partial'
        verified=deliver_ssh(config,json.dumps({'refresh':Spool.tracking,'refresh_result':result}).encode())
        return dict(verified['refresh_result'], refresh_id=refresh_id, attempt_id=attempt_id, source=source)
    finally:
        os.environ.clear();os.environ.update(env_before)
        Spool.tracking=None


class CommandFailed(RuntimeError):
    def __init__(self,returncode):
        super().__init__('collector_failed');self.returncode=returncode


def error_code(exc):
    value=str(exc).lower()
    if isinstance(exc,PermissionError) or 'permission' in value or 'denied' in value: return 'permission_denied'
    if 'auth' in value or 'credential' in value or 'provider_mail_unconfigured' in value: return 'requires_auth'
    if 'schema' in value: return 'unsupported_schema'
    if 'unconfigured' in value: return 'unconfigured'
    if 'busy' in value: return 'collection_busy'
    return 'collector_unavailable'


def bounded_run(argv,timeout=3600,env=None):
    """Disk-backed capped output; kill the process group on timeout."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        child=subprocess.Popen(argv,stdout=out,stderr=err,env=env,start_new_session=True)
        deadline=time.monotonic()+timeout
        try:
            while child.poll() is None:
                if time.monotonic()>deadline or os.fstat(out.fileno()).st_size>65536 or os.fstat(err.fileno()).st_size>65536:
                    raise RuntimeError('collector_timeout_or_output_limit')
                time.sleep(.1)
        except BaseException:
            os.killpg(child.pid,signal.SIGKILL);child.wait();raise
        out.seek(0)
        if child.returncode: raise CommandFailed(child.returncode)
        return out.read(65537).decode('utf-8')


def dispatch(job,config):
    source=job['source'];cfg=config.get('sources',{}).get(source,{})
    if cfg.get('capability')=='local_command':
        argv=cfg.get('command')
        if not isinstance(argv,list) or not argv or any(not isinstance(a,str) for a in argv) or not Path(argv[0]).is_absolute(): raise ValueError('invalid_private_command')
        root=Path(os.environ.get('PERSONAL_CONTEXT_REFRESH_DIR',Path.home()/'.local/share/personal-context-refresh'))
        source_env=cfg.get('env',{})
        if not isinstance(source_env,dict) or any(not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',name) or not isinstance(value,str) for name,value in source_env.items()): raise ValueError('invalid_source_environment')
        env=dict(os.environ)
        env.update(source_env)
        env.update(PERSONAL_CONTEXT_REFRESH_ID=job['refresh_id'],PERSONAL_CONTEXT_REFRESH_ATTEMPT=job['attempt_id'],PERSONAL_CONTEXT_REFRESH_SOURCE=source)
        with resource_lock(root/(source+'-collection.lock')):
            output=bounded_run(argv,timeout=min(int(cfg.get('timeout',3600)),3600),env=env)
        # Exit zero alone does not prove that a pipeline collected its selected scopes.
        for line in reversed(output.splitlines()):
            try: receipt=json.loads(line)
            except ValueError: continue
            if isinstance(receipt,dict) and all(receipt.get(k)==job[k] for k in ('refresh_id','attempt_id','source')):
                return dict(receipt,completion_kind='local_pipeline',upstream_freshness=receipt.get('upstream_freshness','unknown'))
        return {'collection_finished':False,'coverage':'unknown','batch_ids':[],'acked_batch_ids':[],
                'completion_kind':'local_pipeline','error_code':'pipeline_exited_without_receipt','execution_finished':True}

    target=config.get('mac_target','')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*',target): return {'retryable':True}
    python=cfg.get('mac_python',config.get('mac_python'));path=config.get('mac_config')
    if not python or not Path(python).is_absolute() or not path or not Path(path).is_absolute(): raise ValueError('private_mac_runtime_unconfigured')
    remote_env=config.get('mac_env',{})
    if not isinstance(remote_env,dict) or any(not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',k) or not isinstance(v,str) for k,v in remote_env.items()): raise ValueError('invalid_mac_environment')
    remote=shlex.join(['env']+[k+'='+v for k,v in remote_env.items()]+[python,'-m','personal_context.refresh_worker','--run-mac','--source',source,'--refresh-id',job['refresh_id'],'--attempt-id',job['attempt_id'],'--mode',job['mode'],'--config',path])
    try:
        raw=bounded_run(['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=5','-o','ConnectionAttempts=1',target,remote],timeout=3650)
        result=json.loads(raw)
        if any(result.get(k)!=job[k] for k in ('refresh_id','attempt_id','source')):
            return {'error_code':'collector_identity_mismatch','coverage':'unknown'}
        return result
    except CommandFailed as exc:
        return {'retryable':True} if exc.returncode==255 else {'coverage':'unknown','error_code':'mac_worker_unavailable'}
    except OSError: return {'retryable':True}
    except (RuntimeError,ValueError): return {'coverage':'unknown','error_code':'collector_timeout_or_invalid_result'}


def once(c=None):
    c=c or coordinator();c.schedule();job=c.claim(uuid.uuid4().hex)
    if not job: return False
    stop=threading.Event()
    def heartbeat():
        while not stop.wait(30):
            try:
                if not c.heartbeat(job): break
            except (OSError,RuntimeError): pass
    keeper=threading.Thread(target=heartbeat,daemon=True);keeper.start()
    try:
        try: result=dispatch(job,c.config)
        except (OSError,RuntimeError,ValueError,ImportError): result={'error_code':'collector_unavailable','coverage':'unknown'}
        c.finish(job,result)
    finally:
        stop.set();keeper.join(timeout=1)

    return True


def enqueue_scheduled(group,mode='recent',config_path=None):
    """Retain schedule intent locally until Ubuntu durably acknowledges its ID."""
    from .cli import load_config, SERVER_KEY_PATH
    config_path=Path(config_path or Path(os.environ.get('PERSONAL_CONTEXT_CONFIG_DIR',Path.home()/'.config/personal-context-bridge'))/'config.json')
    if config_path.is_symlink() or config_path.stat().st_mode & 0o077: raise ValueError('private_config_required')
    config=load_config(config_path)
    if group not in ('apple','canvas'): raise ValueError('invalid scheduled group')
    root=Path(os.environ.get('PERSONAL_CONTEXT_DATA_DIR',Path.home()/'.local/share/personal-context-bridge'))/'refresh-outbox'
    if root.is_symlink(): raise ValueError('private_outbox_required')
    root.mkdir(parents=True,exist_ok=True,mode=0o700);root.chmod(0o700)
    with resource_lock(root/'queue.lock'):
        # Recover a complete pre-rename write; preserve interrupted bytes separately.
        for orphan in root.glob('.pending-*'):
            if orphan.is_symlink(): raise ValueError('private_outbox_required')
            try:
                item=json.loads(orphan.read_text())
                identity=item.get('request_id') if isinstance(item,dict) else None
                if not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{32}',identity): raise ValueError('invalid orphan')
                final=root/(identity+'.json')
                if final.exists():
                    if final.is_symlink() or final.read_bytes()!=orphan.read_bytes(): raise ValueError('conflicting orphan')
                    orphan.unlink()
                else: os.replace(orphan,final)
            except (ValueError,UnicodeError):
                os.replace(orphan,root/('interrupted-'+uuid.uuid4().hex+'.corrupt'))
        entries={}
        for path in sorted(root.glob('*.json')):
            if path.is_symlink(): raise ValueError('private_outbox_required')
            try:
                item=json.loads(path.read_text())
                if (not isinstance(item,dict) or item.get('request_id')!=path.stem
                        or not re.fullmatch('[a-f0-9]{32}',path.stem)
                        or item.get('group') not in ('apple','canvas')
                        or item.get('mode') not in ('recent','full')): raise ValueError('invalid pending intent')
                entries[path]=item
            except (ValueError,UnicodeError):
                # Keep original bytes for explicit recovery; never block unrelated intent.
                os.replace(path,root/(path.stem+'-'+uuid.uuid4().hex+'.corrupt'))
        existing=next((path for path,item in entries.items() if item['group']==group and item['mode']==mode),None)
        request_id=existing.stem if existing else uuid.uuid4().hex
        pending=root/(request_id+'.json')
        item={'request_id':request_id,'group':group,'mode':mode}
        if not existing:
            fd,name=tempfile.mkstemp(dir=root,prefix='.pending-')
            temporary=Path(name)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(json.dumps(item).encode());stream.flush();os.fsync(stream.fileno())
                os.replace(temporary,pending)
                dirfd=os.open(root,os.O_DIRECTORY)
                try: os.fsync(dirfd)
                finally: os.close(dirfd)
            finally: temporary.unlink(missing_ok=True)
            entries[pending]=item
        remote=Path(config['remote_project'])
        remote_python=config.get('remote_python',str(remote/'.venv/bin/python'))
        for path,item in sorted(entries.items()):
            args=['env','PERSONAL_CONTEXT_KEY_FILE='+SERVER_KEY_PATH]
            if config.get('remote_refresh_config'): args.append('PERSONAL_CONTEXT_REFRESH_CONFIG='+config['remote_refresh_config'])
            if config.get('remote_refresh_dir'): args.append('PERSONAL_CONTEXT_REFRESH_DIR='+config['remote_refresh_dir'])
            args.extend([remote_python,'-m','personal_context.refresh_worker','--request-scheduled',item['group'],'--mode',item['mode'],'--request-id',item['request_id']])
            try:
                response=json.loads(bounded_run(['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=5','-o','ConnectionAttempts=1',config['remote_host'],shlex.join(args)],timeout=20))
                if response.get('requested') is not True or response.get('refresh_id') != item['request_id']: break
            except (OSError,RuntimeError,ValueError): break
            path.unlink()
            dirfd=os.open(root,os.O_DIRECTORY)
            try: os.fsync(dirfd)
            finally: os.close(dirfd)
        return {'queued':True,'local_pending':len(list(root.glob('*.json'))),'request_id':request_id,'corrupt_pending':len(list(root.glob('*.corrupt')))}


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--once',action='store_true');p.add_argument('--enqueue-scheduled',choices=['apple','canvas']);p.add_argument('--request-scheduled',choices=['apple','canvas','obsidian','saved_video']);p.add_argument('--request-id');p.add_argument('--run-mac',action='store_true');p.add_argument('--source');p.add_argument('--refresh-id');p.add_argument('--attempt-id');p.add_argument('--mode',default='recent',choices=['recent','full']);p.add_argument('--config')
    args=p.parse_args(argv)
    if args.enqueue_scheduled:
        print(json.dumps(enqueue_scheduled(args.enqueue_scheduled,args.mode,args.config)));return 0
    if args.request_scheduled:
        c=coordinator()
        sources=[s for s in (MAC_SOURCES[:7] if args.request_scheduled=='apple' else [args.request_scheduled]) if c.config.get('sources',{}).get(s,{}).get('enabled')]
        if not sources: raise ValueError('no_enabled_scheduled_sources')
        print(json.dumps(c.request(sources,args.mode,trigger='scheduled',request_id=args.request_id)));return 0
    if args.run_mac:
        def timed_out(signum,frame): raise RuntimeError('collector_time_limit')
        signal.signal(signal.SIGALRM,timed_out);signal.alarm(3600)
        try: result=run_mac(args.source,args.refresh_id,args.attempt_id,args.mode,args.config)
        except (OSError,RuntimeError,ValueError,ImportError) as exc:
            result={'collection_finished':False,'coverage':'unknown','error_code':error_code(exc)}
            if result['error_code']=='collection_busy': result.update(retryable=True,error_code='collection_busy',phase='waiting_for_resource')
            from .spool import Spool
            if Spool.app_lifecycle is not None: result.update(app_lifecycle=Spool.app_lifecycle,headless=False,gui_fallback=True)
            if args.source=='mail': result.update(upstream_freshness='requires_auth' if result['error_code']=='requires_auth' else 'unknown')
        signal.alarm(0)
        result.update(refresh_id=args.refresh_id,attempt_id=args.attempt_id,source=args.source)
        print(json.dumps(result));return 0
    if not args.once: p.error('--once required')
    once();return 0

if __name__=='__main__': raise SystemExit(main())
