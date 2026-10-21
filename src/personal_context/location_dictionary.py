"""Private place dictionary derived from observed GPS stays, with evidence bounds."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
from .subscription_auth import PrivateState, SignInRequired
from .enrichment import EnrichmentClient, EnrichmentError, canonical


def distance(a,b):
    lat1,lat2=math.radians(a['latitude']),math.radians(b['latitude'])
    dlat=lat2-lat1;dlon=math.radians(b['longitude']-a['longitude'])
    h=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371000*2*math.asin(min(1,math.sqrt(h)))


def build_stays(points, radius=100, dwell=600, max_gap=1800, now=None):
    now=time.time() if now is None else now
    stays=[];group=[]
    def flush():
        if len(group)>=2 and group[-1]['timestamp']-group[0]['timestamp']>=dwell:
            stays.append({'visit_id':hashlib.sha256(('owntracks:'+group[0]['id']).encode()).hexdigest(),
                'start':group[0]['timestamp'],'end':group[-1]['timestamp'],
                'latitude':sum(p['latitude'] for p in group)/len(group),
                'longitude':sum(p['longitude'] for p in group)/len(group),
                'point_count':len(group),'source_ids':[p['id'] for p in group],
                'accuracy_m':max(p['accuracy_m'] for p in group),
                'timing':'observed bounds only; arrival/departure and gaps are uncertain'})
    for p in sorted(points,key=lambda p:(p.get('timestamp') or 0,p['id'])):
        values=[p.get(k) for k in ('timestamp','latitude','longitude','accuracy_m')]
        valid=all(type(v) in (float,int) and math.isfinite(v) for v in values)
        if not valid or not (-90<=p['latitude']<=90 and -180<=p['longitude']<=180 and 0<=p['accuracy_m']<=100 and 0<=p['timestamp']<=now+30):
            flush();group=[];continue
        if group and (p['timestamp']-group[-1]['timestamp']>max_gap or distance(group[0],p)>radius):
            flush();group=[]
        group.append(p)
    flush();return stays


SCHEMA={'type':'object','properties':{'title':{'type':'string'},'summary':{'type':'string'},
        'visit_reason':{'type':'string'}},'required':['title','summary','visit_reason'],'additionalProperties':False}


class LocationDictionary:
    def __init__(self,state=None):
        self.state=state or PrivateState.from_env()

    def load(self):
        return self.state.read('places',{'places':{},'visits':[],'freshness':{},'updated_at':None})

    def update(self,points, freshness=None, geocoder=None, context_lookup=None, client=None, max_enrichments=5):
        with self.state.lock('places'):
            data=self.load();places=data['places'];visits=build_stays(points)
            for place in places.values():place['observation_ids']=[]
            for point in sorted(points,key=lambda p:(p['timestamp'] or 0,p['id'])):
                values=[point.get(k) for k in ('timestamp','latitude','longitude','accuracy_m')]
                if not all(type(v) in (int,float) and math.isfinite(v) for v in values):continue
                if not (0<=point['accuracy_m']<=100 and -90<=point['latitude']<=90 and -180<=point['longitude']<=180 and 0<=point['timestamp']<=time.time()+30):continue
                nearby=[p for p in places.values() if distance(p,point)<=100]
                if nearby:place=min(nearby,key=lambda p:distance(p,point))
                else:
                    pid=str(uuid.uuid4())
                    place={'place_id':pid,'latitude':point['latitude'],'longitude':point['longitude'],
                           'title':'Place '+str(len(places)+1),'aliases':[],'title_source':'unresolved',
                           'description':'Observed location; stay and venue unconfirmed.',
                           'visit_reason':'unknown; GPS does not establish the reason for a visit',
                           'context':[],'correction':{},'observation_ids':[]}
                    places[pid]=place
                place['observation_ids'].append(point['id'])
                if len(place['observation_ids'])==1:place['first_observed']=point['timestamp']
                place['last_observed']=point['timestamp']
            for visit in visits:
                nearby=[p for p in places.values() if distance(p,visit)<=100]
                if nearby:
                    place=min(nearby,key=lambda p:distance(p,visit))
                else:
                    pid=str(uuid.uuid4())
                    place={'place_id':pid,'latitude':visit['latitude'],'longitude':visit['longitude'],
                           'title':'Place '+str(len(places)+1),'aliases':[],'title_source':'unresolved',
                           'description':'Observed stay; venue name has not been verified.',
                           'visit_reason':'unknown; GPS does not establish the reason for a visit',
                           'context':[],'correction':{}}
                    places[pid]=place
                visit['place_id']=place['place_id']
            attempts=0;geocode_attempts=0
            for pid,place in places.items():
                found=[v for v in visits if v['place_id']==pid]
                place['visit_count']=len(found)
                place['observation_count']=len(place.get('observation_ids',[]))
                if not place['observation_count'] and not found:continue
                place['presence']='observed stay' if found else 'location observed; stay unconfirmed'
                place.update(first_seen=min((v['start'] for v in found),default=place.get('first_observed')),last_seen=max((v['end'] for v in found),default=place.get('last_observed')),
                             observed_duration_seconds=sum(v['end']-v['start'] for v in found))
                if geocoder and geocode_attempts<5 and (not place.get('geocoded_at') or time.time()-place['geocoded_at']>90*86400) and time.time()-place.get('geocode_attempt_at',0)>3600:
                    geocode_attempts+=1
                    place['geocode_attempt_at']=time.time()
                    try:
                        resolved=geocoder(place['latitude'],place['longitude'])
                        if resolved and resolved.get('name'):
                            place.update(geocode=resolved,geocoded_at=time.time())
                            if not place['correction'].get('title'):
                                place.update(title=resolved['name'],title_source='Apple Maps geocoder; nearby address, venue may be ambiguous')
                    except (RuntimeError,ValueError,OSError,subprocess.TimeoutExpired):
                        place['geocode_status']='temporarily_unavailable; retry later'
                if context_lookup:place['context']=context_lookup(place,found)[:20]
                info={'place_id':pid,'title':place['title'],'geocode':place.get('geocode'),
                      'visit_count':len(found),'observation_count':place['observation_count'],'presence':place['presence'],'first_seen':place['first_seen'],'last_seen':place['last_seen'],
                      'observed_duration_seconds':place['observed_duration_seconds'],
                      'contexts':place['context'],'correction':place['correction']}
                digest=hashlib.sha256(canonical(info).encode()).hexdigest()
                place['description']=(f"{len(found)} observed stay(s), {place['observed_duration_seconds']//60} observed minutes total. "
                    'Times are sampled bounds, not exact attendance. '+ ('Address resolved by Apple Maps; venue may be ambiguous.' if place.get('geocode') else 'Venue unresolved.'))
                if place['correction'].get('description'):place['description']=place['correction']['description']
                place['generated_is_current']=place.get('enrichment_digest')==digest
                if place.get('enrichment_digest')==digest:
                    place['enrichment_status']='complete'
                elif client and attempts<max_enrichments and time.time()>=place.get('retry_at',0):
                    attempts+=1
                    try:
                        result=client.enrich_json('location_place','Describe the place from provided evidence. Keep the supplied title unless evidence provides a better one. Never invent a venue, visit purpose, identity or relationship. Context matches are tentative. visit_reason must say unknown unless explicitly stated in a cited context; qualify even explicit reasons as source-stated, not confirmed attendance. Use concise plain text.',info,SCHEMA,digest,'1','1')
                        place['generated']=result;place['enrichment_digest']=digest;place['enrichment_status']='complete'
                        place['summary']=result['value']['summary']
                        place['generated_visit_reason']=result['value']['visit_reason']
                        place['retry_count']=0;place['retry_at']=0;place['generated_is_current']=True
                    except SignInRequired:
                        place['enrichment_status']='awaiting_shared_sign_in'
                    except EnrichmentError:
                        place['enrichment_status']='retry_pending'
                        place['retry_count']=place.get('retry_count',0)+1
                        place['retry_at']=time.time()+min(3600,60*2**min(place['retry_count'],6))
                elif not client:place['enrichment_status']='awaiting_shared_sign_in'
                else:place['enrichment_status']='pending'
            data.update(visits=visits,freshness=freshness or {},updated_at=time.time(),source_point_count=len(points))
            self.state.write('places',data)
            return {'place_count':sum(p.get('observation_count',0)>0 for p in places.values()),'visit_count':len(visits),
                    'source_point_count':len(points),'enrichment_attempts':attempts,
                    'awaiting_sign_in':any(p.get('enrichment_status')=='awaiting_shared_sign_in' for p in places.values())}

    def public(self,p,coordinates=False):
        result={k:v for k,v in p.items() if k not in ('latitude','longitude','correction','enrichment_digest','geocode_attempt_at')}
        if not coordinates:result.pop('geocode',None)
        if coordinates:result.update(latitude=p['latitude'],longitude=p['longitude'])
        slug=re.sub(r'[^a-z0-9]+','-',p['title'].casefold()).strip('-')[:60] or 'place'
        result['location_key']=slug+'-'+p['place_id'][:8]
        result['generated_text_is_unverified']=True
        return result

    def search(self,query='',limit=20):
        if not isinstance(limit,int) or not 1<=limit<=100 or len(query)>500:raise ValueError('invalid search bounds')
        data=self.load();terms=query.casefold().split()
        rows=[]
        for p in data['places'].values():
            text=canonical(self.public(p)).casefold()
            if p.get('observation_count',0)>0 and all(t in text for t in terms):rows.append(p)
        rows.sort(key=lambda p:p.get('last_seen',0),reverse=True)
        return {'places':[self.public(p) for p in rows[:limit]],'matched_count':len(rows),
                'updated_at':data['updated_at'],'freshness':data['freshness']}

    def detail(self,place_id,include_coordinates=False):
        p=self.load()['places'].get(place_id)
        return {'found':bool(p),'place':self.public(p,include_coordinates) if p else None}

    def visits(self,place_id='',start=None,end=None,limit=50):
        if type(limit)!=int or not 1<=limit<=200:raise ValueError('limit must be 1..200')
        rows=[v for v in self.load()['visits'] if (not place_id or v['place_id']==place_id)
              and (start is None or v['end']>=start) and (end is None or v['start']<end)]
        return {'visits':[{k:x for k,x in v.items() if k not in ('latitude','longitude')} for v in sorted(rows,key=lambda v:v['start'],reverse=True)[:limit]],'matched_count':len(rows)}

    def correct(self,place_id,title=None,aliases=None,description=None):
        with self.state.lock('places'):
            data=self.load();p=data['places'][place_id]
            for k,v in {'title':title,'aliases':aliases,'description':description}.items():
                if v is not None:
                    if k=='aliases':
                        if not isinstance(v,list) or len(v)>30 or any(not isinstance(a,str) or len(a)>200 for a in v):raise ValueError('invalid aliases')
                    elif not isinstance(v,str) or not 1<=len(v)<=2000:raise ValueError('invalid correction')
                    p[k]=v;p['correction'][k]=v
            p['title_source']='user correction';p['enrichment_status']='pending';p['generated_is_current']=False
            self.state.write('places',data)
        return self.detail(place_id)


def apple_geocode(latitude,longitude):
    target=os.environ.get('PERSONAL_CONTEXT_GEOCODE_SSH_TARGET','')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*',target):
        raise RuntimeError('Apple geocoder SSH target unavailable')
    command='"$HOME/Library/Application Support/Personal Context Bridge/location-geocoder"'
    r=subprocess.run(['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=5',target,command],
        input=json.dumps({'latitude':latitude,'longitude':longitude}).encode(),capture_output=True,timeout=35)
    if r.returncode:raise RuntimeError('Apple reverse geocoder unavailable')
    result=json.loads(r.stdout)
    return {k:str(v)[:1000] for k,v in result.items() if k in ('name','address','locality','country','provider') and v}
