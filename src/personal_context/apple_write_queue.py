"""Encrypted, idempotent outbox for approved native Apple PIM creations."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

DEFAULT_DB = Path.home()/'.local/share/personal-context-bridge/data/apple-writes.sqlite3'
ID = re.compile(r'[0-9a-f]{32}\Z')
DATE = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)\Z')
TERMINAL = ('completed', 'cancelled', 'failed', 'needs_review')
ERRORS = {'delivery_unconfirmed', 'interrupted_delivery', 'native_write_unconfirmed', 'invalid_destination', 'receiver_unavailable', 'request_conflict', 'unsupported_reminder_time'}


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    if not isinstance(value, str) or not DATE.fullmatch(value):
        raise ValueError('date/time must include seconds and a timezone offset')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('timezone offset required')
    return parsed


def validate_payload(kind, payload):
    if kind not in ('calendar', 'reminder') or not isinstance(payload, dict):
        raise ValueError('invalid job kind or fields')
    defaults = {'notes':'', 'alarm_minutes_before': None if kind == 'calendar' else 0}
    defaults.update({'calendar':''} if kind == 'calendar' else {'due_at':'', 'list_name':''})
    allowed = set(defaults) | {'title', 'start_at', 'end_at'} if kind == 'calendar' else set(defaults) | {'title'}
    if set(payload) - allowed:
        raise ValueError('unknown job fields')
    p = defaults | payload
    for name, maximum in [('title', 500), ('notes', 20000), ('calendar' if kind == 'calendar' else 'list_name', 500)]:
        value = p.get(name)
        if not isinstance(value, str) or len(value) > maximum or '\x00' in value or (name == 'title' and not value.strip()):
            raise ValueError('invalid ' + name)
    alarm = p['alarm_minutes_before']
    if alarm is not None and (type(alarm) is not int or not 0 <= alarm <= 10080):
        raise ValueError('alarm must be 0 through 10080 minutes')
    if kind == 'calendar':
        if timestamp(p.get('end_at')) <= timestamp(p.get('start_at')):
            raise ValueError('event end must follow start')
    elif p['due_at']:
        due = timestamp(p['due_at'])
        if due.second or due.microsecond:
            raise ValueError('native reminders require whole-minute due times (seconds 00)')
    elif alarm not in (None, 0):
        raise ValueError('an alarm requires a due time')
    if kind == 'reminder' and not isinstance(p['due_at'], str):
        raise ValueError('invalid due time')
    return p


def canonical(kind, payload):
    return json.dumps({'kind':kind, 'fields':validate_payload(kind, payload)}, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def queue_config(db_path=None, key_file=None):
    path = Path(db_path or os.environ.get('PERSONAL_CONTEXT_APPLE_WRITE_DB', DEFAULT_DB))
    key = Path(key_file or os.environ.get('PERSONAL_CONTEXT_KEY_FILE', ''))
    if not key.is_file() or key.is_symlink() or key.stat().st_mode & 0o077 or len(key.read_bytes()) != 32:
        raise RuntimeError('private 32-byte outbox key required')
    if not path.is_absolute() or path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError('private absolute outbox path required')
    return path, key


@contextmanager
def _db(db_path=None, key_file=None):
    from sqlcipher3 import dbapi2 as sqlcipher
    path, key = queue_config(db_path, key_file)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    db = sqlcipher.connect(str(path), timeout=10)
    try:
        db.execute('PRAGMA key = "x\'' + key.read_bytes().hex() + '\'"')
        db.execute('PRAGMA busy_timeout=10000')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('''CREATE TABLE IF NOT EXISTS apple_writes (
            job_id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, digest TEXT NOT NULL,
            kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error_code TEXT,
            receipt TEXT)''')
        db.commit(); path.chmod(0o600)
        with db:
            yield db
    finally:
        db.close()


def _id(job_id):
    if not isinstance(job_id, str) or not ID.fullmatch(job_id):
        raise ValueError('invalid job ID')


def _status(db, job_id):
    row = db.execute('SELECT state,created_at,updated_at,error_code,receipt FROM apple_writes WHERE job_id=?', (job_id,)).fetchone()
    if row is None:
        return {'job_id':job_id, 'state':'not_found'}
    result = dict(job_id=job_id, state=row[0], created_at=row[1], updated_at=row[2], error_code=row[3])
    if row[4]: result['receipt'] = json.loads(row[4])
    return result


def queue_job(kind, request_key, payload, *, db_path=None, key_file=None, now=None):
    if not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', request_key):
        raise ValueError('invalid request key')
    encoded = canonical(kind, payload)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    created = (now or utcnow()).isoformat()
    with _db(db_path, key_file) as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT job_id,digest,state,created_at FROM apple_writes WHERE request_key=?', (request_key,)).fetchone()
        if old:
            if old[1] != digest: raise ValueError('request key already used with different content')
            return dict(job_id=old[0], state=old[2], created_at=old[3])
        job_id = uuid.uuid4().hex
        db.execute('INSERT INTO apple_writes VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (job_id,request_key,digest,kind,encoded,'queued',created,created,None,None))
    return dict(job_id=job_id, state='queued', created_at=created)


def job_status(job_id, *, db_path=None, key_file=None):
    _id(job_id)
    with _db(db_path, key_file) as db: return _status(db, job_id)


def pending_jobs(*, db_path=None, key_file=None, limit=50):
    if type(limit) is not int or not 1 <= limit <= 100: raise ValueError('invalid limit')
    with _db(db_path, key_file) as db:
        ids = db.execute("SELECT job_id FROM apple_writes WHERE state IN ('queued','delivering','needs_review') ORDER BY created_at LIMIT ?", (limit,)).fetchall()
        return {'pending': [_status(db, row[0]) for row in ids]}


def cancel_job(job_id, *, db_path=None, key_file=None, now=None):
    _id(job_id)
    with _db(db_path, key_file) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE apple_writes SET state='cancelled',payload='',updated_at=? WHERE job_id=? AND state='queued'", ((now or utcnow()).isoformat(),job_id))
        return _status(db, job_id)


def claim_jobs(*, db_path=None, key_file=None, now=None, limit=10):
    if type(limit) is not int or not 1 <= limit <= 100: raise ValueError('invalid limit')
    with _db(db_path, key_file) as db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute("SELECT job_id,kind,payload FROM apple_writes WHERE state='queued' ORDER BY created_at LIMIT ?", (limit,)).fetchall()
        for row in rows:
            db.execute("UPDATE apple_writes SET state='delivering',updated_at=? WHERE job_id=?", ((now or utcnow()).isoformat(), row[0]))
        return [dict(job_id=row[0], kind=row[1], fields=json.loads(row[2])['fields']) for row in rows]


def finish_job(job_id, state, error_code=None, *, receipt=None, db_path=None, key_file=None, now=None):
    _id(job_id)
    if state not in ('completed', 'failed', 'needs_review') or (error_code is not None and error_code not in ERRORS):
        raise ValueError('invalid outcome')
    with _db(db_path, key_file) as db:
        db.execute("UPDATE apple_writes SET state=?,updated_at=?,error_code=?,receipt=?,payload='' WHERE job_id=? AND state='delivering'",
                   (state,(now or utcnow()).isoformat(),error_code,json.dumps(receipt) if receipt else None,job_id))
        return _status(db, job_id)


def recover_interrupted(*, db_path=None, key_file=None):
    """Called only with the worker lock held; never resubmit a crashed delivery."""
    with _db(db_path, key_file) as db:
        db.execute("UPDATE apple_writes SET state='needs_review',error_code='interrupted_delivery',payload='',updated_at=? WHERE state='delivering'", (utcnow().isoformat(),))
