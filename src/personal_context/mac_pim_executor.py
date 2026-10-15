"""Fixed SSH receiver. Native content never enters a shell or receipt journal."""
import argparse
from contextlib import contextmanager
from datetime import timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

from .apple_write_queue import ID, canonical, timestamp, utcnow, validate_payload

MAX_INPUT = 160000
DEFAULT_RECEIPTS = Path.home()/'.local/share/personal-context-bridge/apple-write-receipts/receipts.sqlite3'


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def validate_job(job):
    if not isinstance(job, dict) or set(job) != {'job_id','kind','fields'} or not isinstance(job['job_id'],str) or not ID.fullmatch(job['job_id']):
        raise ValueError('invalid job envelope')
    return dict(job_id=job['job_id'],kind=job['kind'],fields=validate_payload(job['kind'],job['fields']))


def read_job(stream):
    raw = stream.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT: raise ValueError('job too large')
    try: return validate_job(json.loads(raw, object_pairs_hook=_unique))
    except (TypeError, KeyError, json.JSONDecodeError) as exc: raise ValueError('invalid job JSON') from exc


class UnsupportedReminderTime(ValueError):
    pass


def _local_zone():
    with open('/etc/localtime', 'rb') as stream:
        return ZoneInfo.from_file(stream)


def _validate_reminder_time(due):
    # Pinned ReminderCLI writes local components without a timezone/fold. A
    # repeated DST hour cannot retain the approved absolute instant that way.
    try:
        local = timestamp(due).astimezone(_local_zone())
        if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
            raise UnsupportedReminderTime('native reminder cannot represent repeated local hour')
    except (OSError, ValueError) as exc:
        raise UnsupportedReminderTime('native reminder timezone could not be validated') from exc


def _binary(kind):
    name = 'calendar-cli' if kind == 'calendar' else 'reminder-cli'
    path = Path(os.environ.get('PERSONAL_CONTEXT_' + kind.upper() + '_CLI', str(Path.home()/'.local/bin'/name)))
    if not path.is_absolute(): raise ValueError('native CLI path must be absolute')
    return str(path)


def _native(runner, args):
    helper = os.environ.get('PERSONAL_CONTEXT_APPLE_PIM_HELPER', '')
    kwargs = dict(capture_output=True, text=True, timeout=45,
                  env={**os.environ, 'APPLE_PIM_DATE_FORMAT':'utc'})
    if helper:
        if not Path(helper).is_absolute(): raise ValueError('absolute app helper path required')
        # Launch Services assigns TCC responsibility to the already authorized app.
        # Each invocation uses a private output directory and a fresh app instance.
        with tempfile.TemporaryDirectory(prefix='apple-write-') as tmp:
            output, error = Path(tmp)/'out', Path(tmp)/'err'
            output.touch(mode=0o600); error.touch(mode=0o600)
            result = runner(['/usr/bin/open','-n','-W','-a',helper,'--args',
                             Path(args[0]).name,str(output),str(error)]+args[1:], **kwargs)
            with output.open() as stream: raw = stream.read(1024*1024+1)
    else:
        result = runner(args, **kwargs)
        raw = result.stdout
    if len(raw) > 1024*1024 or (not helper and result.returncode):
        raise ValueError('native command failed')
    output = json.loads(raw)
    if not isinstance(output, dict): raise ValueError('invalid native result')
    if helper:
        # open -W can lose its kevent wait race after a short-lived app has
        # already produced a complete result. Trust only the native protocol
        # in our fresh private output file, never the launcher's status alone.
        auth_result = args[1] == 'auth-status' and isinstance(output.get('authorization'), str)
        if output.get('success') is not True and not auth_result:
            raise ValueError('native command did not confirm success')
    return output


def _access(kind, runner):
    binary = _binary(kind)
    auth = _native(runner,[binary,'auth-status'])
    if auth.get('authorization') != 'authorized': raise ValueError('native authorization required')
    config = _native(runner,[binary,'config','show','--format=json']).get('config',{})
    if not isinstance(config,dict) or config.get('calendars',{}).get('mode') != 'all' or config.get('reminders',{}).get('mode') != 'all':
        raise ValueError('broad native access configuration required')
    return binary, config


def health(*, runner=None):
    runner = runner or subprocess.run
    try:
        for kind in ('calendar','reminder'): _access(kind, runner)
        return {'ready':True}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {'ready':False, 'error_code':'receiver_unavailable'}


def _destination(kind, fields, runner, binary, config):
    # Upstream selects the first matching name. Resolve uniquely here and send its ID.
    inventory = _native(runner,[binary,'config','init','--format=json'])
    if inventory.get('success') is not True: raise ValueError('inventory unavailable')
    default_key = 'defaultCalendar' if kind == 'calendar' else 'defaultReminderList'
    explicit_key = 'calendar' if kind == 'calendar' else 'list_name'
    config_key = 'default_calendar' if kind == 'calendar' else 'default_reminder_list'
    wanted = fields[explicit_key] or config.get(config_key) or inventory.get(default_key)
    system_default = not fields[explicit_key] and not config.get(config_key)
    items = inventory.get('availableCalendars' if kind == 'calendar' else 'availableReminderLists', [])
    if not isinstance(wanted,str) or not wanted or not isinstance(items,list): raise ValueError('destination unavailable')
    exact = [x for x in items if x.get('id') == wanted]
    matches = exact or [x for x in items if isinstance(x.get('title'),str) and x['title'].casefold() == wanted.casefold()]
    if system_default:
        # The native API has an unambiguous default object even when its name
        # occurs in several accounts. Omit the flag so EventKit selects it.
        if not matches or any(x.get('allowsModifications') is not True for x in matches):
            raise ValueError('default destination unavailable or read-only')
        return None
    if len(matches) != 1 or matches[0].get('allowsModifications') is not True:
        raise ValueError('destination unavailable or ambiguous')
    value = matches[0].get('id')
    if not isinstance(value,str) or not value or len(value)>2048: raise ValueError('invalid destination ID')
    return value


@contextmanager
def _journal(path):
    path = Path(path or os.environ.get('PERSONAL_CONTEXT_APPLE_RECEIPTS_DB', DEFAULT_RECEIPTS))
    if not path.is_absolute() or path.is_symlink(): raise ValueError('invalid receipt path')
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True); path.parent.chmod(0o700)
    lock_path = path.with_suffix('.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        db = sqlite3.connect(path)
        try:
            path.chmod(0o600)
            db.execute('CREATE TABLE IF NOT EXISTS receipts (job_id TEXT PRIMARY KEY, digest TEXT NOT NULL, receipt TEXT)')
            db.commit()
            yield db
        finally: db.close()


def apply_job(payload, *, receipt_db_path=None, runner=None):
    job = validate_job(payload); job_id = job['job_id']; kind = job['kind']; fields = job['fields']
    digest = hashlib.sha256(canonical(kind,fields).encode()).hexdigest()
    runner = runner or subprocess.run
    with _journal(receipt_db_path) as db:
        prior = db.execute('SELECT digest,receipt FROM receipts WHERE job_id=?',(job_id,)).fetchone()
        if prior:
            if prior[0] != digest: return dict(job_id=job_id,state='needs_review',error_code='request_conflict')
            if prior[1]: return json.loads(prior[1])
            return dict(job_id=job_id,state='needs_review',error_code='native_write_unconfirmed')
        db.execute('INSERT INTO receipts VALUES (?,?,NULL)',(job_id,digest)); db.commit()
        creating = False
        try:
            if kind == 'reminder' and fields['due_at']:
                _validate_reminder_time(fields['due_at'])
            binary, config = _access(kind,runner)
            destination = _destination(kind,fields,runner,binary,config)
            args = [binary,'create','--title='+fields['title']]
            if fields['notes']: args.append('--notes='+fields['notes'])
            due = fields['start_at'] if kind == 'calendar' else fields['due_at']
            if kind == 'calendar':
                args += ['--start='+due,'--end='+fields['end_at']]
                if destination: args.append('--calendar='+destination)
            else:
                if destination: args.append('--list='+destination)
                if due: args.append('--due='+due)
            alarm = fields['alarm_minutes_before']
            if alarm is not None and (kind == 'calendar' or (due and alarm > 0)): args.append('--alarm='+str(alarm))
            creating = True
            output = _native(runner,args)
            item = output.get('event' if kind == 'calendar' else 'reminder',{})
            item_id = item.get('id') if isinstance(item,dict) else None
            if output.get('success') is not True or not isinstance(item_id,str) or not 1 <= len(item_id) <= 2048 or any(ord(c)<32 for c in item_id):
                raise ValueError('native creation unconfirmed')
            alert_at = (timestamp(due)-timedelta(minutes=alarm or 0)).isoformat() if due and (kind == 'reminder' or alarm is not None) else ''
            receipt = dict(job_id=job_id,state='completed',item_id=item_id,completed_at=utcnow().isoformat(),
                           late=bool(due and timestamp(due)<utcnow()),alert_at=alert_at,
                           alert_late=bool(alert_at and timestamp(alert_at)<utcnow()),
                           warnings=['earlier_alarm_display'] if kind == 'reminder' and alarm and alarm>0 else [])
        except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError) as exc:
            receipt = dict(job_id=job_id,state='needs_review' if creating else 'failed',
                           error_code=('native_write_unconfirmed' if creating else
                                       'unsupported_reminder_time' if isinstance(exc, UnsupportedReminderTime) else 'invalid_destination'))
        db.execute('UPDATE receipts SET receipt=? WHERE job_id=?',(json.dumps(receipt),job_id)); db.commit()
        return receipt


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--apply-stdin', action='store_true'); group.add_argument('--health', action='store_true')
    options = parser.parse_args()
    if options.health:
        print(json.dumps(health())); return
    try: result = apply_job(read_job(sys.stdin))
    except (OSError, ValueError, sqlite3.Error):
        print(json.dumps({'state':'rejected','error_code':'receiver_unavailable'})); raise SystemExit(1)
    print(json.dumps(result))


if __name__ == '__main__': main()
