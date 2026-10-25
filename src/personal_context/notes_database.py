"""Read-only CoreData Notes replica snapshots, with strict plaintext decoding.

The gzip protobuf field path follows the schema documented by
https://github.com/threeplanetssoftware/apple_cloud_notes_parser/blob/master/proto/notestore.proto
No credential lookup, cloud fetch, database mutation or locked-note decryption.
"""
import gzip
import os
import plistlib
import sqlite3
import tempfile
import time
import zlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


@contextmanager
def consistent_snapshot(path, timeout=30):
    """SQLite online backup includes committed WAL; never copy a live main file alone."""
    path = Path(path).expanduser().resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='personal-context-notes-') as temporary:
        os.chmod(temporary, 0o700)
        snapshot = Path(temporary) / 'NoteStore.sqlite'
        descriptor = os.open(snapshot, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        deadline = time.monotonic() + timeout
        def progress(status, remaining, total):
            if time.monotonic() >= deadline:
                raise TimeoutError('Notes database snapshot exceeded its deadline')
        source = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
        destination = sqlite3.connect(snapshot)
        try:
            source.execute('PRAGMA query_only=ON')
            source.backup(destination, pages=128, progress=progress, sleep=0.1)
            destination.execute('PRAGMA journal_mode=DELETE')
        finally:
            destination.close()
            source.close()
        yield snapshot


def _varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            break
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, offset
    raise ValueError('unsupported Notes protobuf varint')


def _fields(data):
    offset = 0
    fields = {}
    while offset < len(data):
        tag, offset = _varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if number == 0:
            raise ValueError('invalid Notes protobuf field')
        if wire == 0:
            value, offset = _varint(data, offset)
        elif wire in (1, 2, 5):
            if wire == 2:
                length, offset = _varint(data, offset)
            else:
                length = 8 if wire == 1 else 4
            if length > len(data) - offset:
                raise ValueError('truncated Notes protobuf')
            value = data[offset:offset + length]
            offset += length
        else:
            raise ValueError('unsupported Notes protobuf wire format')
        fields.setdefault(number, []).append((wire, value))
    return fields


def _one(fields, number, wire):
    values = fields.get(number, [])
    if len(values) != 1 or values[0][0] != wire:
        raise ValueError('unsupported Notes protobuf schema')
    return values[0][1]


def decode_note_text(blob):
    """Extract documented plaintext only; reject malformed or unknown structures."""
    if not isinstance(blob, bytes):
        raise ValueError('Notes body is unavailable')
    try:
        stream = zlib.decompressobj(47)  # gzip and zlib wrappers occur in Notes.
        decoded = stream.decompress(blob, 32 * 1024 * 1024 + 1)
        if len(decoded) > 32 * 1024 * 1024 or not stream.eof or stream.unused_data:
            raise ValueError('Notes body exceeds bounds or is truncated')
        document = _fields(_one(_fields(decoded), 2, 2))
        version = _one(document, 2, 0)
        if version != 0:
            # Current Notes document version is 0. Version 1 is also used by
            # documented older schemas and fictional interoperability tests.
            if version != 1:
                raise ValueError('unsupported Notes document version')
        note = _fields(_one(document, 3, 2))
        return _one(note, 2, 2).decode('utf-8')
    except (OSError, EOFError, UnicodeError, zlib.error):
        raise ValueError('unsupported Notes body encoding') from None


def _date(value):
    if not isinstance(value, (int, float)):
        raise ValueError('Notes dates are unavailable')
    return (datetime(2001, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=value)).replace(microsecond=0).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def database_snapshot(snapshot, limit=50000):
    """Produce the existing Notes snapshot contract or reject unsupported coverage.

    Replica freshness remains unknown. Unsupported/locked note bodies are
    unavailable, never empty content; missing identity/folders abort the whole
    snapshot to avoid tombstoning records from an incomplete inventory.
    """
    connection = sqlite3.connect(Path(snapshot).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        required = {'Z_PK', 'Z_ENT', 'ZFOLDER', 'ZNOTEDATA', 'ZTITLE1', 'ZTITLE2', 'ZMARKEDFORDELETION',
                    'ZISPASSWORDPROTECTED', 'ZCREATIONDATE3', 'ZMODIFICATIONDATE1', 'ZNEEDSINITIALFETCHFROMCLOUD'}
        columns = {row[1] for row in connection.execute('PRAGMA table_info(ZICCLOUDSYNCINGOBJECT)')}
        if not required <= columns:
            raise ValueError('unsupported Notes database schema')
        entities = dict(connection.execute('SELECT Z_NAME, Z_ENT FROM Z_PRIMARYKEY'))
        if 'ICNote' not in entities or 'ICFolder' not in entities:
            raise ValueError('unsupported Notes database entities')
        metadata = connection.execute('SELECT Z_UUID, Z_PLIST FROM Z_METADATA').fetchall()
        if len(metadata) != 1:
            raise ValueError('unsupported Notes database metadata')
        plistlib.loads(metadata[0][1])  # reject corrupt CoreData metadata
        store_uuid = metadata[0][0]
        import re
        if not isinstance(store_uuid, str) or not re.fullmatch(r'[A-Fa-f0-9-]{36}', store_uuid):
            raise ValueError('Notes database has no stable CoreData identity')
        rows = connection.execute('''SELECT n.Z_PK, n.ZTITLE1 AS title, n.ZCREATIONDATE3 AS created,
            n.ZMODIFICATIONDATE1 AS modified, n.ZISPASSWORDPROTECTED AS locked,
            n.ZNEEDSINITIALFETCHFROMCLOUD AS initial_fetch, n.ZFOLDER AS folder_id,
            n.ZMARKEDFORDELETION AS deleted, f.ZTITLE2 AS folder, f.ZMARKEDFORDELETION AS folder_deleted,
            d.ZDATA AS data FROM ZICCLOUDSYNCINGOBJECT n
            LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER=f.Z_PK AND f.Z_ENT=?
            LEFT JOIN ZICNOTEDATA d ON n.ZNOTEDATA=d.Z_PK WHERE n.Z_ENT=?''',
            (entities['ICFolder'], entities['ICNote'])).fetchall()
        if len(rows) >= limit:
            raise ValueError('Notes database reached its inventory limit')
        notes, missing = [], 0
        for row in rows:
            if row['initial_fetch'] and row['folder_id'] is None and row['title'] is None:
                # Unmaterialized cloud placeholders aren't exposed by Notes.app.
                continue
            if row['deleted'] or row['folder_deleted'] or row['folder'] == 'Recently Deleted':
                continue
            if not isinstance(row['folder'], str) or not isinstance(row['title'], str):
                raise ValueError('Notes database has incomplete folder/title coverage')
            available = not bool(row['locked']) and row['data'] is not None
            body = ''
            if available:
                # Unknown schemas abort instead of claiming complete extraction.
                body = decode_note_text(row['data'])
            else:
                missing += 1
            notes.append({'id': 'x-coredata://' + store_uuid + '/ICNote/p' + str(row['Z_PK']),
                          'title': row['title'], 'body': body, 'folder': row['folder'],
                          'createdAt': _date(row['created']), 'modifiedAt': _date(row['modified']),
                          'contentAvailable': available})
        return {'success': True, 'count': len(notes), 'notes': notes, 'missingBodies': missing}
    except (sqlite3.Error, plistlib.InvalidFileException, OverflowError, TypeError):
        raise ValueError('unsupported or unavailable Notes database') from None
    finally:
        connection.close()


def legacy_database_snapshot(snapshot, limit=50000, converter='/usr/bin/textutil'):
    """Read older on-device/Exchange Notes store alongside the CloudKit store."""
    import subprocess
    connection = sqlite3.connect(Path(snapshot).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        entities = dict(connection.execute('SELECT Z_ENT, Z_NAME FROM Z_PRIMARYKEY'))
        uuid = connection.execute('SELECT Z_UUID FROM Z_METADATA').fetchone()[0]
        import re
        if not isinstance(uuid, str) or not re.fullmatch(r'[A-Fa-f0-9-]{36}', uuid):
            raise ValueError('legacy Notes has no stable CoreData identity')
        rows = connection.execute('''SELECT n.Z_PK,n.Z_ENT,n.ZTITLE,n.ZDATECREATED,n.ZDATEEDITED,
            f.ZNAME,b.ZHTMLSTRING FROM ZNOTE n
            LEFT JOIN ZFOLDER f ON coalesce(n.ZFOLDER,n.Z6_FOLDER)=f.Z_PK
            LEFT JOIN ZNOTEBODY b ON n.ZBODY=b.Z_PK''').fetchall()
        if len(rows) >= limit:
            raise ValueError('legacy Notes inventory reached its limit')
        notes, missing = [], 0
        for row in rows:
            entity = entities.get(row['Z_ENT'])
            if entity not in {'Note', 'EWSNote', 'IMAPNote'}:
                raise ValueError('unsupported legacy Notes entity')
            if not isinstance(row['ZTITLE'], str) or not isinstance(row['ZNAME'], str):
                raise ValueError('legacy Notes folder/title coverage is incomplete')
            if row['ZNAME'] == 'Recently Deleted':
                continue
            body, available = '', row['ZHTMLSTRING'] is not None
            if available:
                if not isinstance(row['ZHTMLSTRING'], str):
                    raise ValueError('legacy Notes body encoding is unsupported')
                result = subprocess.run([converter, '-convert', 'txt', '-format', 'html', '-encoding', 'UTF-8',
                                         '-stdin', '-stdout'], input=row['ZHTMLSTRING'],
                                        capture_output=True, text=True, timeout=30)
                if result.returncode:
                    raise RuntimeError('legacy Notes text conversion failed')
                body = result.stdout
            else:
                missing += 1
            notes.append({'id': 'x-coredata://' + uuid + '/' + entity + '/p' + str(row['Z_PK']),
                          'title': row['ZTITLE'], 'body': body, 'folder': row['ZNAME'],
                          'bodyFormat': 'legacy-html-textutil', 'bodyHtml': row['ZHTMLSTRING'] or '',
                          'createdAt': _date(row['ZDATECREATED']), 'modifiedAt': _date(row['ZDATEEDITED']),
                          'contentAvailable': available})
        return {'success': True, 'count': len(notes), 'notes': notes, 'missingBodies': missing}
    except sqlite3.Error:
        raise ValueError('unsupported legacy Notes database schema') from None
    finally:
        connection.close()
