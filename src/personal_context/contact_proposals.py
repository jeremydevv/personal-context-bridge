"""Local, encrypted Messages-to-Contacts suggestions. No native write capability.

Run explicitly with a bounded date scope. No model, network, scheduler or outbox
integration. A reviewable suggestion is never an approved native contact patch.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from .identifiers import contact_identifiers, normalize
from .store import Store

POLICY = 'explicit-self-statement-v1'
MONTHS = ('January February March April May June July August September October November December').split()
BIRTHDAY = re.compile(r'My birthday is (?P<value>(?P<month>' + '|'.join(MONTHS) +
                      r') (?P<day>[0-9]{1,2})(?:, (?P<year>[0-9]{4}))?)\.?', re.I)
ADDRESS = re.compile(
    r'My (?P<label>home|work) address is (?P<value>[0-9]{1,6} '
    r"(?:[A-Za-z]+ ){1,6}(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Court|Ct|Way|Boulevard|Blvd|Terrace|Ter|Place|Pl)"
    r'(?: (?:Apt|Unit) [A-Za-z0-9-]{1,12})?'
    r'(?:, [A-Za-z]+(?: [A-Za-z]+){0,3}, [A-Z]{2}(?: [0-9]{5}(?:-[0-9]{4})?)?)?)\.?', re.I)
WRITE_BLOCKERS = ['proposal_only', 'native_identity_unverified', 'native_read_required',
                  'destination_writability_unverified', 'authorization_absent']


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def absolute_time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError('absolute timestamp with offset required') from exc


def candidate(record):
    """Whole-message grammar intentionally abstains from conversational inference."""
    p = record['payload']
    if (not isinstance(p, dict) or p.get('contentAvailable') is not True
            or p.get('fromMe') is not False or p.get('system') is not False
            or p.get('spam') is not False or p.get('service') not in ('iMessage', 'SMS')
            or p.get('retractedAt') or p.get('associatedMessageGuid')
            or p.get('associatedMessageType') not in (None, 0) or p.get('replyToGuid')
            or p.get('attachments') or not isinstance(p.get('sender'), str)):
        return None
    chats = p.get('chats')
    if not isinstance(chats, list) or not chats:
        return None
    for chat in chats:
        if not isinstance(chat, dict) or not isinstance(chat.get('participants'), list):
            return None
        participants = {normalize(v) for v in chat['participants']}
        if None in participants or len(participants) != 1 or normalize(p['sender']) not in participants:
            return None
    text = p.get('text')
    if not isinstance(text, str) or len(text) > 512:
        return None
    match = BIRTHDAY.fullmatch(text)
    if match:
        month = next(i for i, name in enumerate(MONTHS, 1) if name.lower() == match['month'].lower())
        value = {'month': month, 'day': int(match['day'])}
        if match['year']:
            value['year'] = int(match['year'])
        try:
            birthday = date(value.get('year', 2000), month, value['day'])
            if 'year' in value and birthday > absolute_time(record['start']).date():
                return None
        except (ValueError, KeyError):
            return None
        field = 'birthday'
    else:
        match = ADDRESS.fullmatch(text)
        if not match:
            return None
        field = 'postal_address'
        value = {'label': match['label'].lower(), 'formatted': match['value']}
    return {'field': field, 'value': value, 'span_start': match.start('value'),
            'span_end': match.end('value'),
            'span_hash': hashlib.sha256(match['value'].encode()).hexdigest()}


class ProposalPipeline:
    """Owns a SQLCipher proposal ledger and an exclusively read-only source reader."""

    def __init__(self, archive, ledger, key_file):
        archive, ledger, key = map(Path, (archive, ledger, key_file))
        if (key.is_symlink() or not key.is_file() or key.stat().st_mode & 0o077
                or len(key.read_bytes()) != 32):
            raise ValueError('private regular 32-byte encryption key required')
        if (ledger.is_symlink() or ledger.resolve() in (archive.resolve(), key.resolve())
                or ledger.exists() and (not ledger.is_file() or ledger.stat().st_mode & 0o077
                                       or os.path.samefile(ledger, archive)
                                       or os.path.samefile(ledger, key))):
            raise ValueError('private separate ledger required')
        self.archive = Store(archive, key_file=key, read_only=True)
        self.db = None
        try:
            ledger.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not ledger.exists():
                fd = os.open(ledger, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            from sqlcipher3 import dbapi2 as sqlcipher
            self.db = sqlcipher.connect(str(ledger), timeout=10)
            self.db.row_factory = sqlcipher.Row
            self.db.execute('PRAGMA key = "x\'' + key.read_bytes().hex() + '\'"')
            self.db.execute('PRAGMA foreign_keys=ON')
            tables = {row[0] for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and tables != {'proposal_meta', 'proposals', 'evidence', 'proposal_audit'}:
                raise ValueError('existing database is not a proposal ledger')
            if tables:
                meta = dict(self.db.execute('SELECT key,value FROM proposal_meta'))
                if (meta.get('archive') != digest(str(archive.resolve()))
                        or meta.get('schema') != '1'):
                    raise ValueError('ledger archive or schema mismatch')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS proposal_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY, document TEXT NOT NULL, rejected_at TEXT);
                CREATE TABLE IF NOT EXISTS evidence (
                    proposal_id TEXT NOT NULL REFERENCES proposals(id), record_id TEXT NOT NULL,
                    document TEXT NOT NULL, PRIMARY KEY(proposal_id,record_id));
                CREATE TABLE IF NOT EXISTS proposal_audit (
                    sequence INTEGER PRIMARY KEY, proposal_id TEXT NOT NULL,
                    event TEXT NOT NULL, occurred_at TEXT NOT NULL);
            ''')
            expected = digest(str(archive.resolve()))
            old = self.db.execute("SELECT value FROM proposal_meta WHERE key='archive'").fetchone()
            if old and old[0] != expected:
                raise ValueError('ledger belongs to a different archive')
            self.db.execute("INSERT OR IGNORE INTO proposal_meta VALUES ('archive',?)", (expected,))
            self.db.execute("INSERT OR IGNORE INTO proposal_meta VALUES ('schema','1')")
            self.db.commit()
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.db is not None:
            self.db.close()
        self.archive.close()

    def _contacts(self):
        return [dict(row, payload=json.loads(row['payload'])) for row in self.archive.db.execute(
            "SELECT id,payload,digest FROM records WHERE kind='contact' AND source='apple-local' AND deleted=0")]

    def _identity(self, sender, contacts):
        identifier = normalize(sender)
        reasons = []
        if not identifier:
            reasons.append('sender_identifier_invalid')
        elif identifier.startswith('phone:') and not re.fullmatch(r'\+[1-9][0-9]{6,14}', sender):
            reasons.append('phone_requires_international_format')
        matches = [c for c in contacts if identifier and identifier in contact_identifiers(c['payload'])]
        if len(matches) != 1:
            reasons.append('sender_not_unique')
        return (matches[0] if len(matches) == 1 else None), reasons

    def scan(self, start, end, *, limit=500, senders=None):
        start_time, end_time = absolute_time(start), absolute_time(end)
        if not start_time < end_time or end_time - start_time > timedelta(days=31):
            raise ValueError('scope must be positive and at most 31 days')
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('limit must be 1..1000')
        if senders is not None and (not isinstance(senders, list) or not senders
                                   or any(not isinstance(v, str) or not normalize(v) for v in senders)):
            raise ValueError('senders must be a nonempty identifier list')
        # Snapshot pins messages and identity together; never mutate source archive.
        self.archive.db.execute('BEGIN')
        try:
            contacts = self._contacts()
            # SQL returns only bounded metadata first, not every conversation body.
            # SQLite rounds Julian dates to milliseconds. Pad the SQL prefilter by
            # one second, then compare exact timestamps before fetching any payload.
            query = ("SELECT id,start FROM records WHERE kind='message' "
                     "AND source='apple-local' AND deleted=0 "
                     "AND julianday(start)>=julianday(?) AND julianday(start)<julianday(?)")
            params = [(start_time - timedelta(seconds=1)).isoformat(),
                      (end_time + timedelta(seconds=1)).isoformat()]
            if senders is not None:
                query += " AND json_extract(payload,'$.sender') IN (" + ','.join('?' for _ in senders) + ')'
                params.extend(senders)
            query += ' ORDER BY id'
            selected_ids = []
            for row in self.archive.db.execute(query, params):
                try:
                    in_scope = start_time <= absolute_time(row['start']) < end_time
                except ValueError:
                    continue
                if in_scope:
                    selected_ids.append(row['id'])
                    if len(selected_ids) > limit:
                        raise ValueError('scope exceeds limit; narrow scope before scanning')
            selected = []
            for record_id in selected_ids:
                row = self.archive.db.execute(
                    "SELECT id,source,start,payload,digest,captured_at FROM records "
                    "WHERE kind='message' AND id=?", (record_id,)).fetchone()
                selected.append(dict(row, payload=json.loads(row['payload'])))
            count = 0
            with self.db:
                for record in selected:
                    fact = candidate(record)
                    if fact is None:
                        continue
                    p = record['payload']
                    contact, reasons = self._identity(p['sender'], contacts)
                    baseline = None
                    if contact:
                        baseline = contact['digest']
                        if fact['field'] == 'birthday' and contact['payload'].get('birthDate'):
                            reasons.append('existing_birthday_requires_review')
                        if fact['field'] == 'postal_address' and contact['payload'].get('addresses'):
                            reasons.append('existing_address_requires_review')
                    subject = contact['id'] if contact else 'unresolved:' + digest(p['sender'])
                    claim_value = (fact['value'] if fact['field'] == 'birthday' else
                                   dict(fact['value'], formatted=fact['value']['formatted'].casefold()))
                    ident = digest([POLICY, subject, fact['field'], claim_value])
                    document = {'id': ident, 'contact_id': contact['id'] if contact else None,
                                'field': fact['field'], 'value': fact['value'], 'reasons': reasons,
                                'policy': POLICY, 'native_contact_id': None, 'native_account_id': None}
                    evidence = dict(fact, record_id=record['id'], source_digest=record['digest'],
                                    guid=p.get('guid'), sender=p['sender'], sent_at=record['start'],
                                    captured_at=record['captured_at'], contact_digest=baseline,
                                    contact_id=document['contact_id'], identity_reasons=reasons,
                                    scope_start=start_time.isoformat(), scope_end=end_time.isoformat())
                    old = self.db.execute('SELECT document FROM proposals WHERE id=?', (ident,)).fetchone()
                    self.db.execute('INSERT INTO proposals(id,document) VALUES (?,?) '
                                    'ON CONFLICT(id) DO UPDATE SET document=excluded.document',
                                    (ident, encoded(document)))
                    previous = self.db.execute('SELECT document FROM evidence WHERE proposal_id=? AND record_id=?',
                                               (ident, record['id'])).fetchone()
                    self.db.execute('INSERT INTO evidence VALUES (?,?,?) ON CONFLICT(proposal_id,record_id) '
                                    'DO UPDATE SET document=excluded.document', (ident, record['id'], encoded(evidence)))
                    if not old or not previous or json.loads(previous[0]) != evidence:
                        self._audit(ident, 'evidence_recorded')
                    count += 1
            return {'mode': 'proposal_only', 'scanned': len(selected), 'candidates': count,
                    'start': start_time.isoformat(), 'end': end_time.isoformat(), 'write_eligible': False}
        finally:
            self.archive.db.rollback()

    def _audit(self, ident, event):
        self.db.execute('INSERT INTO proposal_audit(proposal_id,event,occurred_at) VALUES (?,?,?)',
                        (ident, event, datetime.now(timezone.utc).isoformat()))

    def _view(self, row, contacts):
        item = json.loads(row['document'])
        evidence = []
        for stored in self.db.execute('SELECT document FROM evidence WHERE proposal_id=? ORDER BY record_id', (item['id'],)):
            e = json.loads(stored[0])
            record = self.archive.db.execute("SELECT id,payload,digest,start FROM records WHERE kind='message' "
                                             "AND source='apple-local' AND id=? AND deleted=0", (e['record_id'],)).fetchone()
            if not record or record['digest'] != e['source_digest'] or item['policy'] != POLICY:
                continue
            record = dict(record, payload=json.loads(record['payload']))
            contact, reasons = self._identity(e['sender'], contacts)
            if ((contact['id'] if contact else None) != e['contact_id']
                    or (contact['digest'] if contact else None) != e['contact_digest']
                    or reasons != [r for r in e['identity_reasons'] if not r.startswith('existing_')]):
                continue
            fact = candidate(record)
            if not fact or fact['span_hash'] != e['span_hash']:
                continue
            e['span'] = record['payload']['text'][e['span_start']:e['span_end']]
            evidence.append(e)
        item.update(evidence=evidence, write_eligible=False, write_blockers=list(WRITE_BLOCKERS))
        item['state'] = ('rejected' if row['rejected_at'] else 'stale' if not evidence
                         else 'blocked' if item['reasons'] else 'reviewable')
        if not evidence:
            item['reasons'] = sorted(set(item['reasons'] + ['evidence_or_identity_changed']))
        return item

    def _views(self):
        self.archive.db.execute('BEGIN')
        try:
            contacts = self._contacts()
            items = [self._view(row, contacts) for row in self.db.execute('SELECT * FROM proposals ORDER BY id')]
            competing = {}
            for item in items:
                if item['state'] in ('blocked', 'reviewable') and item['contact_id']:
                    key = (item['contact_id'], item['field'], item['value'].get('label'))
                    competing.setdefault(key, set()).add(encoded(item['value']))
            for item in items:
                key = (item['contact_id'], item['field'], item['value'].get('label'))
                if item['state'] in ('blocked', 'reviewable') and len(competing.get(key, ())) > 1:
                    item['state'] = 'blocked'
                    item['reasons'] = sorted(set(item['reasons'] + ['competing_claims']))
            return items
        finally:
            self.archive.db.rollback()

    def list(self, *, limit=50, offset=0):
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise ValueError('invalid pagination')
        items = self._views()
        page = [{k: v for k, v in item.items() if k != 'evidence'} for item in items[offset:offset + limit]]
        return {'mode': 'proposal_only', 'proposals': page, 'total': len(items),
                'next_offset': offset + limit if offset + limit < len(items) else None}

    def show(self, proposal_id):
        if not isinstance(proposal_id, str) or not re.fullmatch('[0-9a-f]{64}', proposal_id):
            raise ValueError('invalid proposal ID')
        for item in self._views():
            if item['id'] == proposal_id:
                return item
        raise ValueError('proposal not found')

    def reject(self, proposal_id):
        self.show(proposal_id)
        with self.db:
            result = self.db.execute('UPDATE proposals SET rejected_at=? WHERE id=? AND rejected_at IS NULL',
                                     (datetime.now(timezone.utc).isoformat(), proposal_id))
            if result.rowcount:
                self._audit(proposal_id, 'rejected')
        return self.show(proposal_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'ledger', 'key-file'):
        parser.add_argument('--' + name, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    scan = commands.add_parser('scan', help='explicit bounded local scan; never writes Contacts')
    scan.add_argument('--start', required=True)
    scan.add_argument('--end', required=True)
    scan.add_argument('--limit', type=int, default=500)
    scan.add_argument('--sender', action='append', dest='senders')
    listing = commands.add_parser('list')
    listing.add_argument('--limit', type=int, default=50)
    listing.add_argument('--offset', type=int, default=0)
    for name in ('show', 'reject'):
        commands.add_parser(name).add_argument('proposal_id')
    args = parser.parse_args(argv)
    try:
        with ProposalPipeline(args.archive, args.ledger, args.key_file) as pipeline:
            if args.command == 'scan':
                result = pipeline.scan(args.start, args.end, limit=args.limit, senders=args.senders)
            elif args.command == 'list':
                result = pipeline.list(limit=args.limit, offset=args.offset)
            else:
                result = getattr(pipeline, args.command)(args.proposal_id)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception:
        # Do not print SQL, message text, identifiers or secret paths on errors.
        print('Proposal operation failed; check local paths, key, scope and proposal ID.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
