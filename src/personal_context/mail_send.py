"""Approval-gated Mail outbox with a five-minute cancellation window.

The MCP write call queues exactly one message. Only the separate worker can
submit a due message to the Mac's iCloud Mail account.
"""

import argparse
from contextlib import contextmanager
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


HOLD_SECONDS = 300
ADDRESS = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\Z")
TARGET = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*\Z")
DEFAULT_DB = Path.home() / ".local/share/personal-context-bridge/data/mail-outbox.sqlite3"


def _now():
    return datetime.now(timezone.utc)


def _iso(value):
    return value.isoformat(timespec="microseconds")


def _connection(db_path=None, key_file=None):
    from sqlcipher3 import dbapi2 as sqlcipher

    path = Path(db_path or os.environ.get("PERSONAL_CONTEXT_MAIL_OUTBOX_DB", DEFAULT_DB))
    key_path = Path(key_file or os.environ.get("PERSONAL_CONTEXT_KEY_FILE", ""))
    if not key_path.is_file() or key_path.is_symlink() or key_path.stat().st_mode & 0o077:
        raise RuntimeError("private outbox encryption key is required")
    key = key_path.read_bytes()
    if len(key) != 32:
        raise RuntimeError("outbox encryption key has an invalid length")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.is_symlink():
        raise RuntimeError("outbox path must not be a symlink")
    db = sqlcipher.connect(str(path), timeout=10)
    db.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS mail_outbox (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, due_at TEXT NOT NULL,
        state TEXT NOT NULL, recipients TEXT NOT NULL, subject TEXT NOT NULL,
        body TEXT NOT NULL, updated_at TEXT NOT NULL, error_code TEXT
    )""")
    db.commit()
    path.chmod(0o600)
    return db


@contextmanager
def _db(db_path=None, key_file=None):
    db = _connection(db_path, key_file)
    try:
        with db:
            yield db
    finally:
        db.close()


def _addresses(values, name, required=False):
    if not isinstance(values, list) or (required and not values) or len(values) > 20:
        raise ValueError(name + " must be a list of at most 20 email addresses")
    result = []
    for value in values:
        if not isinstance(value, str) or len(value) > 254 or not ADDRESS.fullmatch(value):
            raise ValueError(name + " contains an invalid email address")
        result.append(value)
    if len(set(value.lower() for value in result)) != len(result):
        raise ValueError(name + " contains duplicate addresses")
    return result


def _message(to, cc, bcc, subject, body):
    to = _addresses(to, "to", required=True)
    cc = _addresses(cc, "cc")
    bcc = _addresses(bcc, "bcc")
    if len(to) + len(cc) + len(bcc) > 30:
        raise ValueError("too many recipients")
    if not isinstance(subject, str) or len(subject) > 998 or "\n" in subject or "\r" in subject:
        raise ValueError("invalid subject")
    if not isinstance(body, str) or not body or len(body) > 200000 or "\x00" in body:
        raise ValueError("invalid plain-text body")
    return {"to": to, "cc": cc, "bcc": bcc}


def queue_email(to, subject, body, cc=None, bcc=None, *, db_path=None, key_file=None, now=None):
    """Queue one exact message after the host's per-call write approval."""
    sender, _ = sender_config()
    recipients = _message(to, [] if cc is None else cc, [] if bcc is None else bcc, subject, body)
    now = now or _now()
    mail_id = uuid.uuid4().hex
    due = now + timedelta(seconds=HOLD_SECONDS)
    with _db(db_path, key_file) as db:
        db.execute("INSERT INTO mail_outbox VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (mail_id, _iso(now), _iso(due), "queued", json.dumps(recipients),
                    subject, body, _iso(now), None))
    return {"id": mail_id, "state": "queued", "from": sender,
            "send_not_before": _iso(due), "cancel_until": _iso(due)}


def pending_emails(*, db_path=None, key_file=None):
    with _db(db_path, key_file) as db:
        rows = db.execute("SELECT id, created_at, due_at, subject FROM mail_outbox "
                          "WHERE state='queued' ORDER BY created_at DESC LIMIT 20").fetchall()
    return {"pending": [{"id": row[0], "created_at": row[1],
                         "send_not_before": row[2], "subject": row[3]} for row in rows]}


def cancel_email(mail_id="", *, db_path=None, key_file=None, now=None):
    """Cancel one queued email; an omitted ID works when exactly one is pending."""
    now = now or _now()
    with _db(db_path, key_file) as db:
        db.execute("BEGIN IMMEDIATE")
        if mail_id:
            if not re.fullmatch(r"[0-9a-f]{32}", mail_id):
                raise ValueError("invalid email ID")
            rows = db.execute("SELECT id, due_at, state FROM mail_outbox WHERE id=?", (mail_id,)).fetchall()
        else:
            rows = db.execute("SELECT id, due_at, state FROM mail_outbox WHERE state='queued' "
                              "ORDER BY created_at DESC LIMIT 2").fetchall()
            if len(rows) > 1:
                choices = db.execute("SELECT id, subject, due_at FROM mail_outbox WHERE state='queued' "
                                     "ORDER BY created_at DESC LIMIT 20").fetchall()
                return {"cancelled": False, "state": "choose_email",
                        "pending": [{"id": item[0], "subject": item[1], "send_not_before": item[2]}
                                    for item in choices]}
        if not rows:
            return {"cancelled": False, "state": "not_found"}
        row = rows[0]
        if row[2] != "queued":
            return {"cancelled": False, "state": row[2]}
        db.execute("UPDATE mail_outbox SET state='cancelled', updated_at=?, body='' WHERE id=? AND state='queued'",
                   (_iso(now), row[0]))
    return {"cancelled": True, "id": row[0], "state": "cancelled"}


def email_status(mail_id, *, db_path=None, key_file=None):
    if not re.fullmatch(r"[0-9a-f]{32}", mail_id):
        raise ValueError("invalid email ID")
    with _db(db_path, key_file) as db:
        row = db.execute("SELECT due_at, state, updated_at, error_code FROM mail_outbox WHERE id=?",
                         (mail_id,)).fetchone()
    if row is None:
        return {"id": mail_id, "state": "not_found"}
    return {"id": mail_id, "send_not_before": row[0], "state": row[1],
            "updated_at": row[2], "error_code": row[3]}


def _as_literal(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def sender_config():
    sender = os.environ.get("PERSONAL_CONTEXT_MAIL_FROM", "")
    account = os.environ.get("PERSONAL_CONTEXT_MAIL_ACCOUNT", "")
    if not ADDRESS.fullmatch(sender) or not account or any(c in account for c in "\r\n\x00"):
        raise ValueError("configure a valid Mail sender and account")
    return sender, account


def _sender_check():
    sender, account = sender_config()
    return ('if ' + _as_literal(sender) + ' is not in (email addresses of account ' +
            _as_literal(account) + ') then error "sender unavailable"')


def _script(recipients, subject, body):
    sender, _ = sender_config()
    lines = ['tell application "Mail"', _sender_check(),
             'set newMessage to make new outgoing message with properties '
             '{subject:' + _as_literal(subject) + ', content:' + _as_literal(body) +
             ', sender:' + _as_literal(sender) + ', visible:false}', 'tell newMessage']
    for kind in ("to", "cc", "bcc"):
        for address in recipients[kind]:
            lines.append('make new ' + kind + ' recipient at end of ' + kind + ' recipients '
                         'with properties {address:' + _as_literal(address) + '}')
    lines += ['if sender is not ' + _as_literal(sender) + ' then error "sender mismatch"',
              'send', 'end tell', 'end tell']
    return "\n".join(lines) + "\n"


def _ssh(target, script, timeout=30):
    return subprocess.run(["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                           "-o", "ConnectTimeout=5", "-o", "ConnectionAttempts=1", target,
                           "/usr/bin/osascript", "-"], input=script, text=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)


def process_due(*, db_path=None, key_file=None, target=None, now=None):
    """Submit due messages once; ambiguous outcomes never retry automatically."""
    target = target or os.environ.get("PERSONAL_CONTEXT_MAIL_SEND_TARGET", "")
    if not TARGET.fullmatch(target):
        raise ValueError("fixed Mail send SSH target is not configured")
    sender_config()
    now = now or _now()
    with _db(db_path, key_file) as db:
        rows = db.execute("SELECT id, recipients, subject, body FROM mail_outbox "
                          "WHERE state='queued' AND due_at<=? ORDER BY due_at LIMIT 10", (_iso(now),)).fetchall()
    results = []
    for mail_id, encoded, subject, body in rows:
        try:
            preflight = _ssh(target, 'tell application "Mail"\n' + _sender_check() + '\nend tell\n', 15)
        except (OSError, subprocess.TimeoutExpired):
            results.append({"id": mail_id, "state": "waiting_for_mac"})
            continue
        if preflight.returncode:
            results.append({"id": mail_id, "state": "waiting_for_mac"})
            continue
        with _db(db_path, key_file) as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute("UPDATE mail_outbox SET state='submitting', updated_at=? "
                                 "WHERE id=? AND state='queued' AND due_at<=?",
                                 (_iso(now), mail_id, _iso(now))).rowcount
        if not updated:
            continue
        try:
            result = _ssh(target, _script(json.loads(encoded), subject, body), 60)
            state = "submitted_to_mail" if result.returncode == 0 else "send_outcome_unknown"
        except (OSError, subprocess.TimeoutExpired):
            state = "send_outcome_unknown"
        with _db(db_path, key_file) as db:
            db.execute("UPDATE mail_outbox SET state=?, updated_at=?, body='', error_code=? WHERE id=? "
                       "AND state='submitting'",
                       (state, _iso(_now()), None if state == "submitted_to_mail" else "mac_send_unconfirmed", mail_id))
        results.append({"id": mail_id, "state": state})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--process-due", action="store_true", required=True)
    parser.parse_args()
    process_due()


if __name__ == "__main__":
    main()
