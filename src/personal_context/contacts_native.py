"""Complete native Contacts fields with read-only note replica coverage.

AddressBook.framework preserves legacy IDs but current macOS may omit the note
property without reporting a usable failure. Never replace it with empty text:
require explicit source databases, complete ID coverage and unambiguous notes.
"""
import sqlite3
from pathlib import Path
from .notes_database import consistent_snapshot


def supplement_contact_notes(value, databases):
    if not isinstance(databases, list) or not databases or any(not isinstance(p, str) or not Path(p).is_absolute() for p in databases):
        raise ValueError('native Contacts requires explicit note_databases for lossless note coverage')
    if not isinstance(value, dict) or not isinstance(value.get('contacts'), list):
        raise ValueError('native Contacts returned malformed data')
    contacts = value['contacts']
    if any(not isinstance(c, dict) or not isinstance(c.get('id'), str) for c in contacts):
        raise ValueError('native Contacts returned malformed identities')
    identifiers = {contact['id'] for contact in contacts}
    notes = {}
    for database in databases:
        with consistent_snapshot(database) as snapshot:
            connection = sqlite3.connect(snapshot.as_uri() + '?mode=ro&immutable=1', uri=True)
            try:
                rows = connection.execute('''SELECT r.ZUNIQUEID,r.ZNOTE,n.Z_PK,n.ZTEXT
                    FROM ZABCDRECORD r LEFT JOIN ZABCDNOTE n ON r.ZNOTE=n.Z_PK''')
                for uid, pointer, note_id, text in rows:
                    if not isinstance(uid, str):
                        continue
                    identifier = uid if uid in identifiers else uid + ':ABPerson'
                    if identifier not in identifiers:
                        continue
                    if pointer is not None and note_id is None:
                        raise ValueError('Contacts note replica has incomplete relationship coverage')
                    if text is not None and not isinstance(text, str):
                        raise ValueError('unsupported Contacts note encoding')
                    body = text or ''
                    if identifier in notes and notes[identifier] != body:
                        raise ValueError('Contacts source replicas disagree on note content')
                    notes[identifier] = body
            except sqlite3.Error:
                raise ValueError('unsupported or unavailable Contacts note database') from None
            finally:
                connection.close()
    if identifiers != notes.keys():
        raise ValueError('Contacts note databases do not cover every native contact identity')
    for contact in contacts:
        contact['note'] = notes[contact['id']]
    return value
