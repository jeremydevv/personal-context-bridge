"""Mac-only integration checks. Creates fictional items in existing defaults and cleans them up."""
from datetime import datetime, timedelta, timezone
import uuid

from personal_context.mac_pim_executor import _bridge, _native, _binary
from personal_context.apple_write_queue import validate_payload


def call(kind, fields):
    result = _bridge(kind, fields, __import__('subprocess').run)
    assert result.get('success') is True, result
    return result


def inspect(kind, item_id, start=None):
    fields = dict(operation='inspect', item_id=item_id)
    if start: fields['occurrence_start_at'] = start
    return call(kind, fields)


def edit(kind, item_id, changes=None, start=None, operation='update', scope='this'):
    current = inspect(kind, item_id, start)
    fields = dict(operation=operation, item_id=item_id, expected_revision=current['revision'])
    if kind == 'calendar': fields.update(occurrence_start_at=start, scope=scope)
    if changes is not None: fields['changes'] = changes
    return call(kind, validate_payload(kind, fields))


def main():
    suffix = uuid.uuid4().hex[:10]
    items = []
    start = '2031-11-02T17:00:00Z'
    # Recover only this check's distinctive fictional fixtures after an uncertain save.
    previous = _native(__import__('subprocess').run, [_binary('calendar'), 'events',
        '--from=2031-11-02', '--to=2031-11-03', '--limit=1000'])
    for event in previous.get('events', []):
        if (event.get('title', '').startswith('Personal Context synthetic check ')
                and event.get('notes') == 'Fictional validation item' and event.get('location') == 'Example location'):
            edit('calendar', event['id'], start=event['startDate'], operation='delete')
    try:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        route = call('calendar', dict(operation='driving_eta', destination='1 Apple Park Way, Cupertino, CA 95014',
            arrival_at=(now + timedelta(hours=2)).isoformat(), origin=dict(latitude=37.7749, longitude=-122.4194,
                age_seconds=0, observed_at=now.isoformat())))['driving']
        assert 1 <= route['seconds'] <= 604800
        for kind in ('calendar', 'reminder'):
            inventory = call(kind, {'operation': 'destinations'})
            assert any(x['writable'] for x in inventory['destinations'])
            fields = dict(title='Personal Context synthetic check ' + suffix, notes='Fictional validation item',
                          alerts=[], timezone='America/New_York')
            if kind == 'calendar': fields.update(start_at=start, end_at='2031-11-02T18:00:00Z', location='Example location')
            else:
                icloud = [r for r in inventory['destinations'] if r['writable'] and r['account'].casefold() == 'icloud']
                assert icloud, 'Private reminder checks require an existing iCloud list'
                fields.update(due_at='2031-11-02T17:00:00Z', priority=5, list_name=icloud[0]['id'])
            created = _bridge(kind, validate_payload(kind, fields), __import__('subprocess').run)
            if created.get('success') is not True:
                if created.get('item_id'): items.append((kind, created['item_id'], start if kind == 'calendar' else None))
                raise AssertionError(created)
            item_id = created['item_id']
            items.append((kind, item_id, start if kind == 'calendar' else None))
            current = inspect(kind, item_id, start if kind == 'calendar' else None)
            again = inspect(kind, item_id, start if kind == 'calendar' else None)
            assert current['revision'] == again['revision'], 'revision changed without an edit'
            patch = {'notes': '', 'title': 'Personal Context updated synthetic check ' + suffix}
            if kind == 'calendar': patch.update(location=route['destination'], alerts=[30], driving=route)
            else: patch.update(priority=1, alerts=[0])
            edited = edit(kind, item_id, patch, start if kind == 'calendar' else None)
            assert edited['verified']
            old = dict(operation='delete', item_id=item_id, expected_revision=current['revision'])
            if kind == 'calendar': old.update(occurrence_start_at=start, scope='this')
            conflict = _bridge(kind, old, __import__('subprocess').run)
            assert conflict.get('error_code') == 'revision_conflict', conflict
            if kind == 'calendar':
                shifted = '2031-11-03T19:00:00Z'
                edit(kind, item_id, {'start_at': shifted, 'end_at': '2031-11-03T20:00:00Z'}, start)
                items.remove((kind, item_id, start))
                start = shifted
                items.append((kind, item_id, start))
                assert inspect(kind, item_id, start)['item']['start_at'].startswith('2031-11-03T19:00:00')
                current_calendar = inspect(kind, item_id, start)['item']['calendar_id']
                alternatives = [d for d in inventory['destinations'] if d['writable'] and d['id'] != current_calendar]
                if alternatives:
                    moved = edit(kind, item_id, {'calendar': alternatives[0]['id']}, start)
                    new_id = moved['item_id']
                    items.remove((kind, item_id, start))
                    item_id = new_id
                    items.append((kind, item_id, start))
                    assert inspect(kind, item_id, start)['item']['calendar_id'] == alternatives[0]['id']
            if kind == 'reminder':
                edit(kind, item_id, {'add_subtasks': [{'title': 'Synthetic child ' + suffix, 'notes': 'Fictional child'}]}, operation='update_private')
                metadata = inspect(kind, item_id)['item']['private_metadata']
                assert len(metadata['subtasks']) == 1
                child_id = metadata['subtasks'][0]['item_id']
                items.append((kind, child_id, None))
                child = inspect(kind, child_id)
                assert child['item']['private_metadata']['parent_id'].lower() == item_id.lower()
                edit(kind, child_id, {'completed': True})
                assert inspect(kind, child_id)['item']['completed'] is True
                edit(kind, child_id, operation='delete')
                items.remove((kind, child_id, None))
                metadata = inspect(kind, item_id)['item']['private_metadata']
                assert metadata['subtasks'] == [], metadata
                edit(kind, item_id, {'urgent': True}, operation='update_private')
                assert inspect(kind, item_id)['item']['private_metadata']['urgent'] is True
                edit(kind, item_id, {'urgent': False}, operation='update_private')
        first, second, third = '2032-11-01T17:00:00Z', '2032-11-08T17:00:00Z', '2032-11-15T17:00:00Z'
        recurring = call('calendar', validate_payload('calendar', dict(title='Personal Context recurring synthetic check ' + suffix,
            notes='Fictional validation item', start_at=first, end_at='2032-11-01T18:00:00Z',
            timezone='UTC', alerts=[], recurrence={'frequency':'weekly', 'count':3})))['item_id']
        items.append(('calendar', recurring, first))
        edit('calendar', recurring, start=second, operation='delete')
        missing = _bridge('calendar', dict(operation='inspect', item_id=recurring, occurrence_start_at=second), __import__('subprocess').run)
        assert missing.get('error_code') == 'item_not_found', missing
        inspect('calendar', recurring, first)
        edit('calendar', recurring, start=third, operation='delete', scope='future')
        inspect('calendar', recurring, first)
        print('Native create, inspect, patch, date/time, calendar move, driving, recurrence scope, conflict, urgent, subtask create/complete/delete passed.')
    finally:
        failures = []
        for kind, item_id, at in reversed(items):
            try: edit(kind, item_id, start=at, operation='delete')
            except Exception: failures.append((kind, item_id))
        if failures: raise RuntimeError('Synthetic cleanup needs review: ' + repr(failures))
        print('Synthetic native items removed.')


if __name__ == '__main__':
    main()
