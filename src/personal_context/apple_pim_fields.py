"""Strict partial-update fields for the native EventKit adapter."""
import math
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

COMMON = {'title', 'notes', 'url', 'alerts', 'recurrence', 'timezone'}
EVENT = COMMON | {'start_at', 'end_at', 'location', 'calendar', 'all_day', 'availability', 'driving'}
REMINDER = COMMON | {'due_at', 'list_name', 'priority', 'completed', 'location_alarm'}
EXTENDED = {'location', 'url', 'alerts', 'recurrence', 'timezone', 'all_day',
            'availability', 'priority', 'completed', 'location_alarm', 'driving'}


def text(value, name, maximum=2048, empty=True):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value or (not empty and not value.strip()):
        raise ValueError('invalid ' + name)
    return value


def changes(kind, fields):
    from .apple_write_queue import timestamp
    if not isinstance(fields, dict) or not fields or set(fields) - (EVENT if kind == 'calendar' else REMINDER):
        raise ValueError('empty or unsupported changes; inspect apple_pim_capabilities')
    for key, value in fields.items():
        if key in ('title', 'notes', 'location', 'calendar', 'list_name', 'url', 'timezone'):
            text(value, key, 20000 if key == 'notes' else 2048,
                 empty=key not in ('title', 'calendar', 'list_name', 'timezone'))
            if key == 'url' and value:
                parsed = urlsplit(value)
                if parsed.scheme not in ('https', 'http') or not parsed.netloc or parsed.username or parsed.password:
                    raise ValueError('URL must be an HTTP(S) URL without credentials')
            if key == 'timezone':
                try: ZoneInfo(value)
                except (ValueError, ZoneInfoNotFoundError) as exc: raise ValueError('unknown timezone') from exc
        elif key in ('start_at', 'end_at', 'due_at'):
            if key == 'due_at' and value == '': continue
            parsed = timestamp(value)
            if kind == 'reminder' and (parsed.second or parsed.microsecond):
                raise ValueError('native reminders require whole-minute times')
        elif key in ('all_day', 'completed'):
            if type(value) is not bool: raise ValueError('invalid ' + key)
        elif key == 'priority':
            if type(value) is not int or value not in (0, 1, 5, 9): raise ValueError('invalid priority')
        elif key == 'availability':
            if value not in ('busy', 'free', 'tentative', 'unavailable'): raise ValueError('invalid availability')
        elif key == 'driving':
            if value is None: continue
            if not isinstance(value, dict) or set(value) != {'seconds', 'computed_at', 'origin_observed_at', 'latitude', 'longitude', 'destination'}:
                raise ValueError('use the automatic driving tool to obtain a verified route')
            if type(value['seconds']) is not int or not 1 <= value['seconds'] <= 604800: raise ValueError('invalid driving duration')
            timestamp(value['computed_at']); timestamp(value['origin_observed_at'])
            text(value['destination'], 'destination', empty=False)
            for name, low, high in [('latitude', -90, 90), ('longitude', -180, 180)]:
                n = value[name]
                if type(n) not in (int, float) or not math.isfinite(n) or not low <= n <= high: raise ValueError('invalid route coordinates')
        elif key == 'alerts':
            if not isinstance(value, list) or len(value) > 5 or any(type(v) is not int or not 0 <= v <= 10080 for v in value):
                raise ValueError('alerts must be at most five minute offsets, or [] to clear')
            if len(set(value)) != len(value): raise ValueError('duplicate alerts')
        elif key == 'recurrence':
            if value is None: continue
            if not isinstance(value, dict) or set(value) - {'frequency', 'interval', 'count', 'until'}:
                raise ValueError('invalid recurrence')
            if value.get('frequency') not in ('daily', 'weekly', 'monthly', 'yearly'):
                raise ValueError('invalid recurrence frequency')
            if type(value.get('interval', 1)) is not int or not 1 <= value.get('interval', 1) <= 999:
                raise ValueError('invalid recurrence interval')
            if 'count' in value and (type(value['count']) is not int or not 1 <= value['count'] <= 10000):
                raise ValueError('invalid recurrence count')
            if 'until' in value: timestamp(value['until'])
            if 'until' in value and 'count' in value: raise ValueError('use count or until')
        elif key == 'location_alarm':
            if value is None: continue
            if not isinstance(value, dict) or set(value) != {'title', 'latitude', 'longitude', 'radius', 'proximity'}:
                raise ValueError('invalid location alarm')
            text(value['title'], 'location title', 500, empty=False)
            for name, low, high in [('latitude', -90, 90), ('longitude', -180, 180), ('radius', 1, 100000)]:
                n = value[name]
                if type(n) not in (int, float) or not math.isfinite(n) or not low <= n <= high:
                    raise ValueError('invalid location ' + name)
            if value['proximity'] not in ('arrive', 'leave'): raise ValueError('invalid proximity')
    if 'start_at' in fields and 'end_at' in fields and timestamp(fields['end_at']) <= timestamp(fields['start_at']):
        raise ValueError('event end must follow start')
    if kind == 'reminder' and fields.get('due_at') == '' and fields.get('alerts'):
        raise ValueError('timed alerts require a due date')
    return fields.copy()


def edit(kind, payload):
    from .apple_write_queue import timestamp
    required = {'operation', 'item_id', 'expected_revision'}
    allowed = required | {'changes'}
    if kind == 'calendar':
        required |= {'occurrence_start_at', 'scope'}
        allowed |= {'occurrence_start_at', 'scope'}
    if not required <= set(payload) or set(payload) - allowed:
        raise ValueError('native edit requires ID, live revision, and calendar occurrence/scope')
    text(payload['item_id'], 'native ID', empty=False)
    if not isinstance(payload['expected_revision'], str) or not re.fullmatch('[0-9a-f]{64}', payload['expected_revision']):
        raise ValueError('inspect the native item to obtain its revision before editing')
    if kind == 'calendar':
        timestamp(payload['occurrence_start_at'])
        if payload['scope'] not in ('this', 'future'): raise ValueError('scope must be this or future')
    if payload['operation'] == 'update_private':
        from .apple_pim_extensions import validate
        patch = payload.get('changes')
        validate(kind, patch)
        if 'urgent' in patch and type(patch['urgent']) is not bool: raise ValueError('invalid urgent flag')
        if 'add_subtasks' in patch:
            children = patch['add_subtasks']
            if not isinstance(children, list) or not 1 <= len(children) <= 50: raise ValueError('supply 1 to 50 subtasks')
            for child in children:
                if not isinstance(child, dict) or 'title' not in child or set(child) - {'title', 'notes'}:
                    raise ValueError('subtasks require title and optional notes')
                text(child['title'], 'subtask title', 500, empty=False)
                if 'notes' in child: text(child['notes'], 'subtask notes', 20000)
        return payload.copy()
    if payload['operation'] == 'update':
        return payload | {'changes': changes(kind, payload.get('changes'))}
    if payload['operation'] != 'delete' or 'changes' in payload: raise ValueError('invalid operation')
    return payload.copy()
