"""Fictional Calendar snapshots: bounded authoritative removal, never native writes."""
import copy
from pathlib import Path
import tempfile
import unittest

from personal_context.collect import collect_recent_calendar
from personal_context.store import Store


class CalendarReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'archive.sqlite3')
        self.addCleanup(self.store.close)

    def item(self, native, start, calendar='example', title='Fictional meeting'):
        return {'id': native, 'title': title, 'calendarId': calendar,
                'startDate': start, 'endDate': start, 'notes': 'Fictional fixture'}

    def seed(self, items, scope='calendar:example:2024-2026'):
        from personal_context.collect import _record
        self.store.ingest({'schema': 1, 'source': 'apple-pim', 'kind': 'calendar',
                           'scope': scope, 'complete': True, 'collected_at': '2026-10-01T00:00:00Z',
                           'records': [_record('calendar', x) for x in items]})

    def recent(self, items, **overrides):
        def run(args):
            if args[1] == 'list':
                return {'success': True, 'calendars': [{'id': 'example'}]}
            return {'success': True, 'events': items,
                    'dateRange': {'from': '2026-10-01T04:00:00Z', 'to': '2026-11-01T03:59:59Z'},
                    **overrides}
        return collect_recent_calendar(run, ['example'], '2026-10-01', '2026-10-31',
                                       '1970-01-01', '2100-12-31', '2026-10-02T00:00:00Z')[0]

    def test_successful_recent_scan_removes_deleted_and_obsolete_timed_occurrences(self):
        # Without bounded removal the deleted occurrence and old timed identity stay visible.
        timed = self.item('same-native', '2026-10-12T13:00:00Z')
        deleted = self.item('deleted', '2026-10-13T12:00:00Z')
        normal = self.item('normal', '2026-10-14T12:00:00Z')
        all_day = self.item('same-native', '2026-10-12T04:00:00Z')
        self.seed([timed, deleted, normal])
        self.store.ingest(self.recent([all_day, normal]))
        self.assertEqual(['same-native|2026-10-12T04:00:00Z', 'normal|2026-10-14T12:00:00Z'],
                         [x['id'] for x in self.store.upcoming('2026-10-01', '2026-11-01')])
        self.assertIsNone(self.store.get('calendar', 'deleted|2026-10-13T12:00:00Z'))
        self.assertTrue(self.store.get('calendar', 'same-native|2026-10-12T13:00:00Z', include_deleted=True)['deleted'])
        self.assertEqual(2, self.store.version_count('calendar', 'deleted|2026-10-13T12:00:00Z'))
        self.assertEqual(2, len(self.store.search('Fictional')))

    def test_empty_authoritative_window_only_retires_matching_calendar_and_start_bounds(self):
        self.seed([self.item('before', '2026-10-01T03:59:59Z'),
                   self.item('at-start', '2026-10-01T00:00:00-04:00'),
                   self.item('inside', '2026-10-20T08:00:00-04:00'),
                   self.item('at-end', '2026-11-01T03:59:59Z'),
                   self.item('old', '2024-01-01T00:00:00Z')])
        self.seed([self.item('other', '2026-10-20T12:00:00Z', calendar='other')], 'calendar:other:2024-2026')
        self.store.ingest(self.recent([]))
        for id in ['at-start|2026-10-01T00:00:00-04:00', 'inside|2026-10-20T08:00:00-04:00']:
            self.assertIsNone(self.store.get('calendar', id))
        for id in ['before|2026-10-01T03:59:59Z', 'at-end|2026-11-01T03:59:59Z',
                   'old|2024-01-01T00:00:00Z', 'other|2026-10-20T12:00:00Z']:
            self.assertIsNotNone(self.store.get('calendar', id))

    def test_partial_batch_without_authority_preserves_missing_records(self):
        self.seed([self.item('keep', '2026-10-20T12:00:00Z')])
        batch = self.recent([])
        batch.pop('calendar_window', None)
        self.store.ingest(batch)
        self.assertIsNotNone(self.store.get('calendar', 'keep|2026-10-20T12:00:00Z'))

    def test_failed_truncated_or_missing_range_collection_never_removes_archive(self):
        self.seed([self.item('keep', '2026-10-20T12:00:00Z')])
        for overrides in [{'success': False}, {'dateRange': None}, {'complete': False},
                          {'truncated': True}, {'hasMore': True}, {'count': 5},
                          {'dateRange': {'from': '2026-10-01', 'to': '2026-11-01'}}]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.recent([], **overrides)
        def truncated(args):
            return ({'success': True, 'calendars': [{'id': 'example'}]} if args[1] == 'list'
                    else {'success': True, 'events': [self.item('a', '2026-10-02T12:00:00Z'),
                                                      self.item('b', '2026-10-03T12:00:00Z')]})
        with self.assertRaisesRegex(ValueError, 'limit'):
            collect_recent_calendar(truncated, ['example'], '2026-10-01', '2026-10-31',
                                    '1970-01-01', '2100-12-31', '2026-10-02T00:00:00Z', limit=2)
        self.assertIsNotNone(self.store.get('calendar', 'keep|2026-10-20T12:00:00Z'))

    def test_foreign_calendar_in_authoritative_batch_is_rejected_atomically(self):
        self.seed([self.item('keep', '2026-10-20T12:00:00Z')])
        batch = self.recent([self.item('new', '2026-10-21T12:00:00Z')])
        batch['records'][0]['payload']['calendarId'] = 'other'
        with self.assertRaises(ValueError):
            self.store.ingest(batch)
        self.assertIsNotNone(self.store.get('calendar', 'keep|2026-10-20T12:00:00Z'))
        self.assertIsNone(self.store.get('calendar', 'new|2026-10-21T12:00:00Z'))

    def test_window_validation_fails_before_any_ingestion(self):
        self.seed([self.item('keep', '2026-10-20T12:00:00Z')])
        good = self.recent([])
        for window in [None, {}, {'start': '2026-10-01', 'end': '2026-11-01'},
                       {'start': '2026-11-01T00:00:00Z', 'end': '2026-10-01T00:00:00Z'}]:
            with self.subTest(window=window), self.assertRaises(ValueError):
                self.store.ingest(dict(good, calendar_window=window))
        wrong_calendar = copy.deepcopy(good)
        wrong_calendar.update(kind='reminder')
        with self.assertRaises(ValueError):
            self.store.ingest(wrong_calendar)
        self.assertIsNotNone(self.store.get('calendar', 'keep|2026-10-20T12:00:00Z'))

    def test_inconsistent_occurrence_identity_is_rejected_before_tombstoning(self):
        self.seed([self.item('keep', '2026-10-20T12:00:00Z')])
        good = self.recent([self.item('new', '2026-10-21T12:00:00Z')])
        for field, value in [('id', 'wrong-occurrence'), ('start', '2026-10-22T12:00:00Z')]:
            bad = copy.deepcopy(good)
            bad['records'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.store.ingest(bad)
        self.assertIsNotNone(self.store.get('calendar', 'keep|2026-10-20T12:00:00Z'))
        self.assertEqual(1, len(self.store.search('Fictional')))

    def test_authoritative_window_preserves_another_year_scope(self):
        self.seed([self.item('keep', '2026-10-20T12:00:00Z')], 'calendar:example:2025-2027')
        self.store.ingest(self.recent([]))
        self.assertIsNotNone(self.store.get('calendar', 'keep|2026-10-20T12:00:00Z'))

    def test_older_snapshot_cannot_resurrect_a_bounded_deletion(self):
        old = self.item('gone', '2026-10-20T12:00:00Z')
        self.seed([old])
        self.store.ingest(self.recent([]))
        replay = self.recent([old])
        replay['collected_at'] = '2026-10-01T12:00:00Z'
        self.store.ingest(replay)
        self.assertIsNone(self.store.get('calendar', 'gone|2026-10-20T12:00:00Z'))
