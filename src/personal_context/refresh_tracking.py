"""Encrypted durable refresh intent. Execution and source freshness are independent."""
import contextlib
import fcntl
import json
import os
import re
import time
import uuid
from pathlib import Path

SOURCES = ('calendar','reminder','contact','mail','message','note','voice_memo','canvas','obsidian','saved_video','health','location','google_timeline','icloud_drive','summaries')
MAC_SOURCES = SOURCES[:8]
ACTIVE = ('queued','waiting','running','interrupted')
CAPABILITIES = {'health':'waiting_for_device','location':'waiting_for_device','google_timeline':'manual_import_required','icloud_drive':'requires_auth','summaries':'derived_processing'}


def private_config():
    path = os.environ.get('PERSONAL_CONTEXT_REFRESH_CONFIG')
    if not path: return {'sources': {}}
    path = Path(path)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError('private refresh config required')
    return json.loads(path.read_text())


class Coordinator:
    def __init__(self, state, config=None, clock=time.time):
        self.state, self.config, self.clock = state, config or {}, clock

    @contextlib.contextmanager
    def locked(self):
        fd = os.open(self.state.path('refresh', '.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as lock:
            end = time.monotonic()+5
            while True:
                try:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); break
                except BlockingIOError:
                    if time.monotonic()>=end: raise RuntimeError('refresh_ledger_busy')
                    time.sleep(.025)
            ledger=self.state.read('refresh',{'requests':{},'baselines':{}})
            try:
                yield ledger
                self.state.write('refresh',ledger)
            finally: fcntl.flock(lock,fcntl.LOCK_UN)

    def _root_child(self, data, request_id, source):
        seen = set()
        while True:
            if request_id in seen: raise RuntimeError('refresh_join_cycle')
            seen.add(request_id)
            child = data['requests'][request_id]['sources'][source]
            joined = child.get('joined_to')
            if not joined: return request_id, child
            request_id = joined

    def _view(self, r, data):
        children = {}
        for source in r['sources']:
            root, child = self._root_child(data, r['refresh_id'], source)
            children[source] = dict(child)
            if root != r['refresh_id']: children[source]['joined_refresh_id'] = root
        states = [j['state'] for j in children.values()]
        state = ('complete' if all(x == 'complete' for x in states) else
                 'running' if 'running' in states else
                 'queued' if 'queued' in states else
                 'waiting' if any(x in ACTIVE for x in states) else
                 'partial' if any(x in ('complete', 'partial') for x in states) else 'failed')
        return dict(r, sources=children, state=state, requested=True)

    def request(self,sources,mode='recent',trigger='manual',request_id=None):
        if mode not in ('recent','full'): raise ValueError('mode must be recent or full')
        if not isinstance(sources,list) or any(s not in SOURCES for s in sources): raise ValueError('unknown refresh source')
        enabled=self.config.get('sources',{})
        sources=sorted(set(sources or [s for s,v in enabled.items() if v.get('enabled')]))
        if not sources: raise ValueError('no enabled refresh sources')
        now=self.clock()
        with self.locked() as data:
            if request_id and request_id in data['requests']:
                existing=data['requests'][request_id]
                if existing['mode']!=mode or sorted(existing['sources'])!=sources: raise ValueError('request_identity_conflict')
                return self._view(existing, data)
            def dispatchable(child):
                return child.get('capability') in ('mac','local_command')
            def in_flight(child):
                return dispatchable(child) and child['state'] in ACTIVE
            equivalent = next((parent for parent in data['requests'].values()
                               if parent['mode'] == mode and sorted(parent['sources']) == sources
                               and any(in_flight(self._root_child(data,parent['refresh_id'],source)[1]) for source in sources)
                               and all(not dispatchable(child) or child['state'] in ACTIVE
                                       for child in (self._root_child(data,parent['refresh_id'],source)[1] for source in sources))), None)
            if equivalent and not request_id: return self._view(equivalent, data)
            active_roots = {(root,source) for parent in data['requests'].values()
                            for source in parent['sources']
                            for root,child in [self._root_child(data,parent['refresh_id'],source)]
                            if in_flight(child)}
            if len(active_roots)>=1000: raise RuntimeError('refresh_queue_full')
            rid=request_id or uuid.uuid4().hex
            if not isinstance(rid,str) or len(rid)!=32 or any(c not in '0123456789abcdef' for c in rid): raise ValueError('invalid request identity')
            jobs={}
            for source in sources:
                if equivalent:
                    root, _ = self._root_child(data, equivalent['refresh_id'], source)
                    jobs[source] = {'source': source, 'joined_to': root}
                    continue
                shared = next((self._root_child(data, parent['refresh_id'], source)[0]
                               for parent in data['requests'].values()
                               if parent['mode'] == mode and source in parent['sources']
                               and self._root_child(data, parent['refresh_id'], source)[1]['state'] in ACTIVE), None)
                if shared:
                    jobs[source] = {'source': source, 'joined_to': shared}
                    continue
                cfg=enabled.get(source,{})
                capability=cfg.get('capability',CAPABILITIES.get(source,'unconfigured'))
                if cfg.get('enabled') is False: capability='disabled'
                dispatch=(capability=='mac' and source in MAC_SOURCES) or (capability=='local_command' and source in ('obsidian','saved_video'))
                jobs[source]={'source':source,'state':'queued' if dispatch else 'waiting' if capability=='waiting_for_device' else 'failed','phase':'queued' if dispatch else capability,'error_code':None if dispatch else capability,'attempts':0,'retry_at':now,'capability':capability}
            r={'refresh_id':rid,'mode':mode,'trigger':trigger,'created_at':now,'sources':jobs,'explicit_id':bool(request_id)}
            data['requests'][rid]=r
            # Keep idempotency identities and any root referenced by a joined request.
            referenced = {j['joined_to'] for parent in data['requests'].values()
                          for j in parent['sources'].values() if j.get('joined_to')}
            terminal = [key for key, parent in data['requests'].items()
                        if key not in referenced and not parent.get('explicit_id')
                        and not any(self._root_child(data,key,source)[1]['state'] in ACTIVE
                                    for source in parent['sources'])]
            for old in terminal[:-500]: del data['requests'][old]
            return self._view(r, data)

    def status(self,rid):
        with self.locked() as data:
            if rid not in data['requests']: return {'refresh_id':rid,'state':'unknown','requested':False}
            return self._view(data['requests'][rid], data)

    def claim(self,owner):
        now=self.clock()
        with self.locked() as data:
            for rid,r in data['requests'].items():
                for source,j in r['sources'].items():
                    if j.get('joined_to'): continue
                    if j.get('capability') not in ('mac','local_command'): continue
                    if j['state']=='running' and j.get('lease_until',0)<=now:
                        j.update(state='interrupted',error_code='lease_expired',retry_at=now,interruptions=j.get('interruptions',0)+1)
                        if j['interruptions']>=3:
                            j.update(state='failed',phase='failed',error_code='interruption_limit');continue
                    if j['state'] in ('queued','waiting','interrupted') and j['retry_at']<=now:
                        j.update(state='running',phase='collecting',attempts=j['attempts']+1,attempt_id=uuid.uuid4().hex,lease_owner=owner,lease_until=now+3700,heartbeat=now)
                        return dict(j,refresh_id=rid,mode=r['mode'])
        return None

    def heartbeat(self,job):
        with self.locked() as data:
            child=data['requests'][job['refresh_id']]['sources'][job['source']]
            if child.get('attempt_id')!=job['attempt_id'] or child['state']!='running': return False
            child.update(heartbeat=self.clock(),lease_until=self.clock()+3700)
            return True

    def finish(self,job,result):
        with self.locked() as data:
            r=data['requests'][job['refresh_id']]; j=r['sources'][job['source']]
            if j.get('attempt_id')!=job['attempt_id'] or j['state']!='running': return False
            now=self.clock()
            if result.get('retryable'):
                j.update(state='waiting',phase=result.get('phase','waiting_for_device'),error_code=result.get('error_code','device_unavailable'),retry_at=now+min(300,30*2**min(j['attempts'],4)))
            else:
                batches=result.get('batch_ids',[]); acks=result.get('acked_batch_ids',[])
                complete=(result.get('collection_finished') is True and result.get('coverage')=='complete' and set(batches)==set(acks))
                j.update(state='complete' if complete else 'partial' if batches or result.get('collection_finished') or result.get('execution_finished') else 'failed',phase=result.get('completion_kind','archive_acknowledged') if complete else 'partial',error_code=None if complete else (result.get('error_code','incomplete_coverage') if re.fullmatch('[a-z_]{1,64}',str(result.get('error_code','incomplete_coverage'))) else 'incomplete_coverage'),finished_at=now,batches=len(batches),acknowledged_batches=len(acks),coverage=result.get('coverage','unknown'),completion_kind=result.get('completion_kind','archive_acknowledged'))
                for field in ('headless_mode','headless','gui_fallback','app_lifecycle','attachment_processing','upstream_freshness','local_replica_only','archive_verified','completion_kind'):
                    if field in result: j[field]=result[field]
                if complete: data['baselines'][job['source']]={'refresh_id':job['refresh_id'],'acknowledged_at':now}
            return True

    def schedule(self):
        """Persist queue intent before advancing each configured schedule watermark."""
        now=self.clock()
        for schedule in self.config.get('schedules',[]):
            name=schedule.get('name','')
            if not isinstance(name,str) or not name or len(name)>64: raise ValueError('invalid schedule name')
            interval=schedule.get('interval_seconds')
            if not isinstance(interval,(int,float)) or interval<60: raise ValueError('invalid schedule interval')
            with self.locked() as data:
                previous=data.get('schedules',{}).get(name)
            if previous is not None and now-previous<interval: continue
            self.request(schedule.get('sources',[]),schedule.get('mode','recent'),trigger='scheduled')
            with self.locked() as data:
                data.setdefault('schedules',{})[name]=now

    def sources(self,source='all'):
        if source!='all' and source not in SOURCES: raise ValueError('unknown source')
        with self.locked() as data:
            out={}
            for s in SOURCES if source=='all' else [source]:
                cfg=self.config.get('sources',{}).get(s,{})
                latest=next((r for r in reversed(list(data['requests'].values())) if s in r['sources']),None)
                base=data['baselines'].get(s)
                out[s]={'capability':cfg.get('capability',CAPABILITIES.get(s,'unconfigured')),'enabled':cfg.get('enabled',False),'refresh':self._view(latest,data)['sources'][s] if latest else None,'baseline':base,'freshness':'unknown' if not base else 'fresh' if self.clock()-base['acknowledged_at']<86400 else 'stale','upstream_freshness':self._root_child(data,latest['refresh_id'],s)[1].get('upstream_freshness','unknown') if latest else 'unknown','derived_processing':'separate'}
            return {'configured':bool(self.config.get('sources')),'sources':out}


def coordinator():
    from .subscription_auth import PrivateState
    keypath=Path(os.environ['PERSONAL_CONTEXT_KEY_FILE'])
    if keypath.is_symlink() or keypath.stat().st_mode & 0o077: raise ValueError('private archive key required')
    root=os.environ.get('PERSONAL_CONTEXT_REFRESH_DIR',str(Path.home()/'.local/share/personal-context-refresh'))
    return Coordinator(PrivateState(root,keypath.read_bytes()),private_config())


def request_refresh(sources,mode='recent'): return coordinator().request(sources,mode)
def refresh_status(refresh_id): return coordinator().status(refresh_id)
def source_status(source='all',database=None):
    try:
        result=coordinator().sources(source)
        if database:
            from .store import Store
            try:
                store=Store(database,read_only=True)
                try:
                    for name,entry in result['sources'].items():
                        entry['archive_collected_at']=store.last_sync(name) if name in MAC_SOURCES else None
                        entry['source_freshness']='unknown'
                        entry['ingestion']=dict(acknowledged_refresh=entry.get('baseline'),archive_collected_at=entry['archive_collected_at'])
                        entry['summary_processing']='separate'
                finally: store.close()
            except FileNotFoundError: pass
        return result
    except (KeyError,FileNotFoundError):
        if source!='all' and source not in SOURCES: raise ValueError('unknown source')
        return {'configured':False,'sources':{s:{'capability':CAPABILITIES.get(s,'unconfigured'),'freshness':'unknown','refresh':None,'upstream_freshness':'unknown'} for s in SOURCES if source=='all' or s==source}}
