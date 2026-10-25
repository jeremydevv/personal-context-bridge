"""Read-only configured Canvas collection through the shared durable archive spool.

Configuration and tokens belong in the private runtime, never in the checkout.
The public runner does not replace an operator's separately maintained collector.
"""
import fcntl
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import httpx

from .canvas_collect import CanvasClient, collect_batches
from .cli import deliver_ssh
from .spool import Spool


def _protected_json(path):
    path=Path(path).expanduser()
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError('Canvas configuration must be private')
    return json.loads(path.read_text())


def load_accounts(path):
    value=_protected_json(path)
    accounts=value.get('accounts') if isinstance(value,dict) else None
    if not isinstance(accounts,list) or not accounts: raise ValueError('Canvas accounts are unconfigured')
    labels=set()
    for account in accounts:
        if not isinstance(account,dict): raise ValueError('invalid Canvas account configuration')
        label=account.get('label','')
        if not isinstance(label,str) or not re.fullmatch('[a-z][a-z0-9_-]{0,31}',label) or label in labels:
            raise ValueError('invalid or duplicate Canvas account label')
        labels.add(label)
        url=urlsplit(account.get('base_url',''))
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):
            raise ValueError('Canvas origin must be HTTPS')
        if not isinstance(account.get('token_file'),str) or not account['token_file']:
            raise ValueError('Canvas token file required')
        if 'user_id' in account and (not isinstance(account['user_id'],int) or isinstance(account['user_id'],bool)):
            raise ValueError('invalid Canvas user ID')
        for flag in ('download_files','extended'):
            if flag in account and not isinstance(account[flag],bool): raise ValueError('invalid Canvas collection option')
    return accounts


def _partial(value):
    if isinstance(value,dict):
        if any(value.get(key) in ('partial','unavailable','failed') for key in ('status','content_status','extraction_status')):
            return True
        return any(_partial(v) for v in value.values())
    if isinstance(value,list): return any(_partial(v) for v in value)
    return False


def run(config_dir=None,data_dir=None):
    config_dir=Path(config_dir or os.environ.get('PERSONAL_CONTEXT_CONFIG_DIR',Path.home()/'.config/personal-context-bridge'))
    data_dir=Path(data_dir or os.environ.get('PERSONAL_CONTEXT_DATA_DIR',Path.home()/'.local/share/personal-context-bridge'))
    data_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(data_dir/'canvas-sync.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return {'already_running':True,'collection_finished':False,'coverage':'partial','accounts':0,'failed':0,'pending':0}
        config=_protected_json(config_dir/'config.json')
        if not re.fullmatch('[A-Za-z0-9_.-]+',config.get('remote_host','')) or not Path(config.get('remote_project','')).is_absolute():
            raise ValueError('invalid Canvas archive transport configuration')
        accounts=load_accounts(config_dir/'canvas-accounts.json')
        spool=Spool(data_dir/'spool'/'canvas')
        complete=failed=0;partial=False
        try: spool.flush(lambda payload:deliver_ssh(config,payload))
        except (OSError,RuntimeError,ValueError):
            return {'collection_finished':False,'coverage':'partial','accounts':0,'failed':0,'pending':len(spool.pending()),'error_code':'archive_unavailable'}
        for account in accounts:
            client=None
            try:
                token=Path(account['token_file']).expanduser()
                if token.is_symlink() or token.stat().st_mode & 0o077: raise ValueError('private Canvas token required')
                client=CanvasClient(account['base_url'],token.read_text().strip())
                batches=collect_batches(client,account['label'],download_files=account.get('download_files',False),extended=account.get('extended',True))
                scopes={(batch.get('kind'),batch.get('scope')) for batch in batches}
                for course_batch in batches:
                    if course_batch.get('kind')!='canvas_course': continue
                    for record in course_batch.get('records',[]):
                        course_id=record.get('payload',{}).get('id')
                        if course_id is not None and any((kind,account['label']+':course:'+str(course_id)) not in scopes for kind in ('canvas_assignment','canvas_announcement','canvas_file')): partial=True
                for batch in batches:
                    if _partial(batch): partial=True
                    spool.enqueue([batch])
                    spool.flush(lambda payload:deliver_ssh(config,payload))
                complete+=1
            except (OSError,RuntimeError,ValueError,httpx.HTTPError): failed+=1
            finally:
                if client is not None: client.close()
        pending=len(spool.pending())
        return {'collection_finished':True,'coverage':'partial' if partial or failed or pending else 'complete','accounts':complete,'failed':failed,'pending':pending}


def main():
    print(json.dumps(run()))

if __name__=='__main__': main()
