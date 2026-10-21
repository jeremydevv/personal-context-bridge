"""Incremental cached enrichment worker. Never logs coordinates or source text."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
import time
from .subscription_auth import AuthSession, PrivateState
from .enrichment import EnrichmentClient
from .location_dictionary import LocationDictionary, apple_geocode
from .store import Store


def context_lookup(place,visits):
    """Exact place aliases plus bounded visit-time overlap; association is tentative."""
    dbpath=os.environ.get('PERSONAL_CONTEXT_DB')
    if not dbpath:return []
    aliases=[place['title']]+place.get('aliases',[])
    aliases=[x.casefold() for x in aliases if len(x)>=4 and not x.startswith('Place ')]
    if not aliases:return []
    store=Store(dbpath,read_only=True)
    try:
        candidates=[]
        # Source title/body remain untrusted; only bounded evidence excerpts leave this reader.
        for kind,rid,title,body,start,end,digest in store.db.execute(
            "SELECT kind,id,title,body,start,end,digest FROM records WHERE deleted=0 AND kind IN ('calendar','message','note','voice_memo') ORDER BY captured_at DESC LIMIT 20000"):
            text=(title+'\n'+body).casefold()
            if not any(alias in text for alias in aliases):continue
            overlap=False
            if start:
                try:
                    dt=datetime.fromisoformat(start.replace('Z','+00:00'))
                    if dt.tzinfo is not None:
                        ts=dt.timestamp();overlap=any(v['start']-7200<=ts<=v['end']+7200 for v in visits)
                except ValueError:pass
            if kind in ('calendar','message') and not overlap:continue
            candidates.append({'kind':kind,'record_id':rid,'title':title[:200],'excerpt':body[:500],
                               'source_digest':digest,'association':'tentative alias match'+(' with time overlap' if overlap else ''),
                               'attendance_or_reason_confirmed':False})
            if len(candidates)>=20:break
        return candidates
    finally:store.close()


def run_once():
    from iphone_context.read_mcp import open_archive
    from iphone_context.queries import TravelQueries
    state=PrivateState.from_env()
    with state.lock('location-worker'):
        db=open_archive('travel')
        try:
            count=db.execute("SELECT count(*) FROM events WHERE event_type='location'").fetchone()[0]
            if count>200000:raise RuntimeError('Location archive exceeds processing bound; partition before continuing')
            points=[dict(zip(('id','timestamp','latitude','longitude','accuracy_m'),r)) for r in db.execute(
                "SELECT digest,event_ts,lat,lon,accuracy FROM events WHERE event_type='location' ORDER BY event_ts")]
            freshness=TravelQueries(db).status()
        finally:db.close()
        auth=AuthSession(state)
        client=EnrichmentClient(state=state,auth=auth) if auth.status()['plan_usage_enabled'] else None
        result=LocationDictionary(state).update(points,freshness=freshness,
            geocoder=apple_geocode if os.environ.get('PERSONAL_CONTEXT_GEOCODE_SSH_TARGET') else None,
            context_lookup=context_lookup,client=client)
        state.write('location-worker-status',dict(result,checked_at=time.time(),state='ready' if client else 'awaiting_shared_sign_in'))
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--correct-place')
    parser.add_argument('--title')
    parser.add_argument('--alias',action='append')
    args=parser.parse_args()
    if args.correct_place:
        LocationDictionary().correct(args.correct_place,title=args.title,aliases=args.alias)
        print(json.dumps({'corrected':True}))
    else:print(json.dumps(run_once(),sort_keys=True))

if __name__=='__main__':main()
