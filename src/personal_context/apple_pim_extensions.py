"""Bounded native-only changes, including encrypted inline attachment transport."""
import base64
import binascii
import hashlib
import re
from pathlib import PurePath

MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 4 * 1024 * 1024
TAG = re.compile(r'[\w-]{1,80}\Z', re.UNICODE)
EMAIL = re.compile(r'[^\s@<>"\\,;:]+@[^\s@<>"\\,;:]+\.[^\s@<>"\\,;:]+\Z')


def strings(values, name, *, empty=False, maximum=50):
    if not isinstance(values, list) or not (0 if empty else 1) <= len(values) <= maximum:
        raise ValueError('invalid ' + name)
    if any(not isinstance(s, str) or not s or len(s) > 2048 or any(ord(c) < 32 for c in s) for s in values):
        raise ValueError('invalid ' + name)
    if len({s.casefold() for s in values}) != len(values): raise ValueError('duplicate ' + name)
    return values


def attachment(spec, kind):
    if not isinstance(spec, dict) or set(spec) != {'filename', 'media_type', 'content_base64', 'sha256'}:
        raise ValueError('attachments require filename, media_type, content_base64 and sha256; paths/URLs are not accepted')
    name = spec['filename']
    if (not isinstance(name, str) or not 1 <= len(name) <= 150 or name in ('.', '..')
            or any(c in name for c in '/\\:') or any(ord(c) < 32 for c in name)):
        raise ValueError('invalid attachment filename')
    types = {'image/png': ('.png', b'\x89PNG\r\n\x1a\n'), 'image/jpeg': ('.jpg', b'\xff\xd8\xff')}
    if kind == 'calendar': types['application/pdf'] = ('.pdf', b'%PDF-')
    if not isinstance(spec['media_type'], str) or spec['media_type'] not in types:
        raise ValueError('unsupported native attachment type')
    suffix, magic = types[spec['media_type']]
    if PurePath(name).suffix.lower() not in ((suffix, '.jpeg') if suffix == '.jpg' else (suffix,)):
        raise ValueError('attachment extension does not match media type')
    value = spec['content_base64']
    if not isinstance(value, str) or len(value) > 4 * ((MAX_FILE + 2)//3): raise ValueError('attachment exceeds 2 MiB')
    try: data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc: raise ValueError('invalid attachment encoding') from exc
    if not 1 <= len(data) <= MAX_FILE or not data.startswith(magic): raise ValueError('invalid attachment bytes')
    if not isinstance(spec['sha256'], str) or hashlib.sha256(data).hexdigest() != spec['sha256']:
        raise ValueError('attachment hash mismatch')
    return len(data)


def validate(kind, patch):
    allowed = {'add_attachments', 'remove_attachments'} | (
        {'urgent', 'add_subtasks', 'set_tags', 'add_tags', 'remove_tags'} if kind == 'reminder'
        else {'add_attendees', 'remove_attendees', 'allow_invitation_delivery'})
    if not isinstance(patch, dict) or not patch or set(patch) - allowed:
        raise ValueError('unsupported native-only changes')
    for key in ('set_tags', 'add_tags', 'remove_tags'):
        if key in patch:
            strings(patch[key], key, empty=key == 'set_tags')
            if any(not TAG.fullmatch(tag) for tag in patch[key]): raise ValueError('tags use letters, numbers, underscores or hyphens without #')
    if 'set_tags' in patch and set(patch) & {'add_tags', 'remove_tags'}: raise ValueError('replace tags or add/remove, not both')
    if set(map(str.casefold, patch.get('add_tags', []))) & set(map(str.casefold, patch.get('remove_tags', []))):
        raise ValueError('cannot add and remove the same tag')
    if 'add_attendees' in patch:
        attendees = patch['add_attendees']
        if not isinstance(attendees, list) or not 1 <= len(attendees) <= 50: raise ValueError('supply 1 to 50 attendees')
        emails = []
        for person in attendees:
            if not isinstance(person, dict) or 'email' not in person or set(person) - {'email', 'name'}:
                raise ValueError('attendee requires email and optional name')
            emails.append(person['email'])
            if 'name' in person: strings([person['name']], 'attendee name')
        strings(emails, 'attendee emails')
        if any(not EMAIL.fullmatch(email) for email in emails): raise ValueError('invalid attendee email')
    if 'remove_attendees' in patch:
        strings(patch['remove_attendees'], 'attendee emails')
        if any(not EMAIL.fullmatch(email) for email in patch['remove_attendees']): raise ValueError('invalid attendee email')
    if {p['email'].casefold() for p in patch.get('add_attendees', [])} & {e.casefold() for e in patch.get('remove_attendees', [])}:
        raise ValueError('cannot add and remove the same attendee')
    if set(patch) & {'add_attendees', 'remove_attendees'} and patch.get('allow_invitation_delivery') is not True:
        raise ValueError('attendee changes require explicit invitation/cancellation delivery consent')
    if 'allow_invitation_delivery' in patch and type(patch['allow_invitation_delivery']) is not bool:
        raise ValueError('invalid invitation consent')
    if set(patch) == {'allow_invitation_delivery'}: raise ValueError('no changes')
    if 'add_attachments' in patch:
        specs = patch['add_attachments']
        if not isinstance(specs, list) or not 1 <= len(specs) <= 5: raise ValueError('supply 1 to 5 attachments')
        if sum(attachment(spec, kind) for spec in specs) > MAX_TOTAL: raise ValueError('attachment batch exceeds 4 MiB')
        if len({spec['sha256'] for spec in specs}) != len(specs): raise ValueError('duplicate attachment bytes')
    if 'remove_attachments' in patch: strings(patch['remove_attachments'], 'attachment IDs')
    return patch
