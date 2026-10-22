"""Shared GET-only student resources, coverage and summary integration.

The reader owns bounded same-origin pagination, including wrapped list APIs.
403/404 preserve old snapshots; unexpected failures abort the collection.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
from urllib.parse import quote

from .canvas_modules import CanvasAPIError, _plain, _id

BASE_KINDS = ('course','assignment','announcement','file','conversation','module','module_item','page')
COURSE_KINDS = ('submission','discussion','discussion_entry','syllabus','assignment_group',
                'grading_period','grading_standard','file_inventory','folder','section','user','tab','quiz','quiz_submission')
ACCOUNT_KINDS = ('planner_item','planner_note','planner_override','todo','missing_submission','group','calendar_event')
KINDS = BASE_KINDS + COURSE_KINDS + ACCOUNT_KINDS + ('collection_state',)
CANVAS_KINDS = tuple('canvas_'+kind for kind in KINDS)
SUMMARY_METADATA_KEYS = frozenset(('rubric','rubric_assessment','submission_comments','submission_history',
    'assignment_group_id','group_weight','rules','grading_scheme','weight','start_date','end_date',
    'plannable','plannable_type','plannable_id','planner_override','marked_complete','dismissed',
    'content_status','position','module_id','prerequisite_module_ids','completion_requirement',
    'completion_requirements','state','type','content_details','linked_record_id','parent_id',
    'topic_id','attempt','score','grade','attachments','context_code','time_limit','allowed_attempts'))

def summary_kinds():
    """Explicit opt-in prevents extension processing during a user sync hold."""
    if os.environ.get('PERSONAL_CONTEXT_CANVAS_EXTENDED_SUMMARIES') != '1':
        return ()
    return tuple('canvas_'+kind for kind in ('module','module_item','page')+COURSE_KINDS+ACCOUNT_KINDS)

def _rows(value, wrapper=None):
    if wrapper and isinstance(value,dict):
        value=value.get(wrapper)
    if not isinstance(value,list) or len(value)>10000 or any(not isinstance(v,dict) for v in value):
        raise ValueError('invalid or oversized Canvas resource list')
    return value

def _text(value):
    """Keep nested feedback/history searchable without dropping structured fields."""
    if isinstance(value,str):return _plain(value)
    if isinstance(value,list):return '\n'.join(filter(None,(_text(v) for v in value)))
    if isinstance(value,dict):
        return '\n'.join(_text(v) for k,v in value.items()
                         if k in ('body','comment','message','description','details','title','name','submission_comments','submission_history'))
    return ''

def collect_resources(read, account, courses, assignments, stamp, linked_pages=(), *, include_account=True, account_only=False):
    """Collect all audited feature families. No external URLs are followed.

    Windowed planner/calendar batches are non-authoritative outside their window.
    Successful unbounded lists are complete; partial nested lists never retire old
    entries. Page batches merge module-linked pages with the full index/front page.
    """
    if not re.fullmatch(r'[A-Za-z0-9_-]+',account):raise ValueError('invalid Canvas account label')
    now=datetime.fromisoformat(stamp.replace('Z','+00:00'))
    if now.tzinfo is None:raise ValueError('collection time must include timezone')
    window={'start':(now-timedelta(days=30)).date().isoformat(),
            'end':(now+timedelta(days=180)).date().isoformat()}
    batches=[]
    prefix='canvas:'+account+':'

    def record(kind, item, cid=None, locator=None, body=None, **extra):
        locator=str(locator if locator is not None else _id(item.get('id')))
        rid=prefix+kind+(':'+str(cid) if cid is not None else '')+':'+locator
        payload=dict(item,account=account,**extra)
        if cid is not None:payload['course_id']=cid
        return {'id':rid,'title':str(item.get('title') or item.get('name') or item.get('display_name') or item.get('label') or kind.replace('_',' ')),
                'body':_text(item) if body is None else body,'payload':payload,
                'start':item.get('due_at') or item.get('plannable_date') or item.get('todo_date') or item.get('start_at') or item.get('created_at'),
                'end':item.get('end_at')}

    def emit(kind,scope,records,complete=True):
        if len({r['id'] for r in records})!=len(records):raise ValueError('duplicate Canvas resource ID')
        batch=dict(schema=1,source='canvas-lms',kind='canvas_'+kind,scope=scope,
                   collected_at=stamp,complete=complete,records=records)
        if kind in ('planner_item','calendar_event') and states[kind]['status']=='available':
            batch['canvas_window']={k:v+'T00:00:00Z' for k,v in window.items()}
            # Canvas date filters may include the end date. Keep the archived
            # authoritative range half-open, with an explicit exclusive end.
            end=datetime.fromisoformat(batch['canvas_window']['end'].replace('Z','+00:00'))+timedelta(days=1)
            batch['canvas_window']['end']=end.isoformat().replace('+00:00','Z')
        batches.append(batch)

    def fetch(states,kind,path,params=None,wrapper=None,single=False):
        try:
            data=read(path,params or {})
            if single:
                if not isinstance(data,dict):raise ValueError('invalid Canvas resource record')
            else:data=_rows(data,wrapper)
            states[kind]={'status':'available','checked_at':stamp}
            return data
        except CanvasAPIError as exc:
            if exc.status not in (403,404):raise
            states[kind]={'status':'unavailable','http_status':exc.status,'checked_at':stamp}
            return None

    for course in (() if account_only else courses):
        cid=int(_id(course.get('id')));root='courses/'+str(cid);scope=account+':course:'+str(cid)
        states={}
        for kind,endpoint,wrapper in (
            ('assignment_group','assignment_groups',None),('grading_period','grading_periods','grading_periods'),
            ('grading_standard','grading_standards',None),('file_inventory','files',None),
            ('folder','folders',None),('section','sections',None),('user','users',None),('tab','tabs',None),('quiz','quizzes',None)):
            data=fetch(states,kind,root+'/'+endpoint,{'per_page':100},wrapper)
            if data is None:continue
            records=[record(kind,item,cid,locator=str(item['id']) if kind=='tab' else None,
                            **({'linked_record_id':prefix+'file:'+str(cid)+':'+_id(item.get('id'))} if kind=='file_inventory' else {})) for item in data]
            emit(kind,scope,records)
            if kind=='quiz':
                submissions=[];complete=True
                for item in data:
                    qid=_id(item.get('id'));key='quiz_submission:'+qid
                    found=fetch(states,key,root+'/quizzes/'+qid+'/submissions',{'per_page':100},'quiz_submissions')
                    if found is None:complete=False;continue
                    submissions.extend(record('quiz_submission',v,cid,locator=qid+':'+_id(v.get('id')),quiz_id=item['id']) for v in found)
                states['quiz_submission']={'status':'available' if complete else 'partial','checked_at':stamp}
                emit('quiz_submission',scope,submissions,complete)

        detail=fetch(states,'syllabus',root,{'include[]':['syllabus_body','total_scores','course_progress']},single=True)
        if detail is not None:
            emit('syllabus',scope,[record('syllabus',detail,cid,locator=str(cid),body=_plain(detail.get('syllabus_body') or ''))])

        pages={r['id']:r for b in linked_pages if b['scope']==scope for r in b['records']}
        page_index=fetch(states,'page',root+'/pages',{'per_page':100})
        page_complete=page_index is not None
        for item in page_index or []:
            slug=item.get('url')
            if not isinstance(slug,str) or not slug or slug in ('.','..') or len(slug)>1024:raise ValueError('invalid Canvas page locator')
            encoded=quote(slug,safe='');key='page:'+encoded
            page=fetch(states,key,root+'/pages/'+encoded,single=True)
            if page is None:
                page=dict(item,content_status='unavailable',http_status=states[key]['http_status'])
            else:page=dict(page,content_status='locked' if page.get('locked_for_user') else 'available')
            row=record('page',page,cid,locator=encoded,body=_plain(page.get('body') or ''))
            pages[row['id']]=row
        front=fetch(states,'front_page',root+'/front_page',single=True)
        if front is not None:
            slug=front.get('url')
            if not isinstance(slug,str) or not slug or slug in ('.','..') or len(slug)>1024:raise ValueError('invalid Canvas front page locator')
            front=dict(front,front_page=True,content_status='locked' if front.get('locked_for_user') else 'available')
            row=record('page',front,cid,locator=quote(slug,safe=''),body=_plain(front.get('body') or ''))
            pages[row['id']]=row
        if pages or page_complete:emit('page',scope,list(pages.values()),page_complete)

        submission_rows=[];complete=True
        for assignment in assignments.get(cid,[]):
            aid=_id(assignment.get('id'));key='submission:'+aid
            data=fetch(states,key,root+'/assignments/'+aid+'/submissions/self',
                       {'include[]':['submission_comments','submission_history','rubric_assessment']},single=True)
            if data is None:complete=False;continue
            submission_rows.append(record('submission',data,cid,locator=aid,assignment_id=int(aid),
                linked_record_id=prefix+'assignment:'+str(cid)+':'+aid))
        states['submission']={'status':'available' if complete else 'partial','checked_at':stamp}
        emit('submission',scope,submission_rows,complete)

        topics=fetch(states,'discussion',root+'/discussion_topics',{'per_page':100})
        if topics is not None:
            emit('discussion',scope,[record('discussion',v,cid) for v in topics])
            entries={};complete=True
            for topic in topics:
                tid=_id(topic.get('id'));key='discussion_entry:'+tid
                found=fetch(states,key,root+'/discussion_topics/'+tid+'/entries',{'per_page':100})
                if found is None:complete=False;continue
                for entry in found:
                    eid=_id(entry.get('id'))
                    row=record('discussion_entry',entry,cid,locator=tid+':'+eid,topic_id=int(tid))
                    entries[row['id']]=row
                    replies=entry.get('recent_replies') or []
                    if entry.get('has_more_replies'):
                        replies=fetch(states,key+':'+eid,root+'/discussion_topics/'+tid+'/entries/'+eid+'/replies',{'per_page':100})
                        if replies is None:complete=False;replies=[]
                    for reply in _rows(replies):
                        row=record('discussion_entry',reply,cid,locator=tid+':'+_id(reply.get('id')),topic_id=int(tid),parent_id=int(eid))
                        entries[row['id']]=row
            states['discussion_entry']={'status':'available' if complete else 'partial','checked_at':stamp}
            emit('discussion_entry',scope,list(entries.values()),complete)
        emit('collection_state',scope,[record('collection_state',{'id':cid},cid,locator='status',features=states)])

    if not include_account:return batches
    states={}
    for kind,path,params in (
        ('planner_item','planner/items',{'start_date':window['start'],'end_date':window['end']}),
        ('planner_note','planner_notes',{}),('planner_override','planner/overrides',{}),
        ('todo','users/self/todo',{}),('missing_submission','users/self/missing_submissions',{}),
        ('group','users/self/groups',{}),
        ('calendar_event','calendar_events',{'type':'event','start_date':window['start'],'end_date':window['end'],
          'context_codes[]':['course_'+_id(v.get('id')) for v in courses]})):
        data=fetch(states,kind,path,dict(params,per_page=100))
        if data is None:continue
        if kind=='calendar_event':
            personal=fetch(states,'personal_calendar_event',path,{'type':'event','start_date':window['start'],'end_date':window['end'],'per_page':100})
            if personal is None:states[kind]['status']='partial'
            else:data=list({v['id']:v for v in [*data,*personal]}.values())
        records=[]
        for item in data:
            if kind in ('planner_item','todo'):
                nested=item.get('plannable') or item.get('assignment') or {}
                identity=[item.get('course_id',nested.get('course_id')),item.get('plannable_type') or item.get('type'),item.get('plannable_id',nested.get('id'))]
                if identity[-1] is None:raise ValueError('Canvas planner/to-do identity missing')
                locator=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:32]
                row=record(kind,dict(item,title=nested.get('title') or nested.get('name') or kind),locator=locator)
            else:row=record(kind,item)
            records.append(row)
        windowed=kind in ('planner_item','calendar_event')
        if windowed:states[kind]['window']=window
        emit(kind,account,records,not windowed)
    emit('collection_state',account,[record('collection_state',{},locator='status',features=states)])
    return batches
