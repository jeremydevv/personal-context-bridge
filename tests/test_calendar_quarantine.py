"""Fictional fixtures for explicitly reviewed, private archive quarantine."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from personal_context.store import Store


class CalendarQuarantineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'archive.sqlite3')
        self.addCleanup(self.store.close)
        self.batch = {
            'schema': 1, 'source': 'apple-pim', 'kind': 'calendar',
            'scope': 'calendar:fictional:2027-2029', 'complete': True,
            'collected_at': '2026-10-01T00:00:00Z',
            'records': [self.item('obsolete'), self.item('keep')],
        }
        self.store.ingest(self.batch)
        record = self.store.db.execute(
            'SELECT digest FROM records WHERE id=?', (self.item('obsolete')['id'],)).fetchone()
        self.guard = {
            'schema': 1, 'source': 'apple-pim', 'kind': 'calendar',
            'scope': self.batch['scope'],
            'expected_id_digest': {self.item('obsolete')['id']: record['digest']},
        }

    def item(self, native):
        start = '2027-01-04T12:00:00Z'
        return {'id': native + '|' + start, 'title': 'Fictional meeting',
                'body': 'Fictional content', 'start': start, 'end': start,
                'payload': {'id': native, 'calendarId': 'fictional',
                            'startDate': start, 'endDate': start}}

    def install(self):
        path = self.root / 'calendar-quarantine.json'
        path.write_text(json.dumps(self.guard))
        path.chmod(0o600)
        return path

    def fresh(self):
        batch = copy.deepcopy(self.batch)
        batch['collected_at'] = '2026-10-02T00:00:00Z'
        return batch

    def test_known_payload_is_retired_and_cannot_be_reintroduced(self):
        self.install()
        self.store.ingest(self.fresh())
        self.assertIsNone(self.store.get('calendar', self.item('obsolete')['id']))
        self.assertIsNotNone(self.store.get('calendar', self.item('keep')['id']))
        self.assertEqual(1, len(self.store.search('Fictional')))
        self.store.ingest(dict(self.fresh(), collected_at='2026-10-03T00:00:00Z'))
        self.assertIsNone(self.store.get('calendar', self.item('obsolete')['id']))
        self.assertEqual(2, self.store.version_count('calendar', self.item('obsolete')['id']))

    def test_changed_payload_fails_before_any_write(self):
        self.install()
        batch = self.fresh()
        batch['records'][0]['title'] = 'Changed legitimate meeting'
        batch['records'].insert(0, self.item('new'))
        with self.assertRaisesRegex(ValueError, 'changed; review required'):
            self.store.ingest(batch)
        self.assertIsNone(self.store.get('calendar', self.item('new')['id']))
        self.assertIsNotNone(self.store.get('calendar', self.item('obsolete')['id']))
        self.assertEqual(1, self.store.version_count('calendar', self.item('obsolete')['id']))

    def test_new_occurrence_and_other_scope_pass(self):
        self.install()
        batch = self.fresh()
        batch['records'].append(self.item('new'))
        self.store.ingest(batch)
        self.assertIsNotNone(self.store.get('calendar', self.item('new')['id']))
        batch = self.fresh()
        batch['scope'] = 'calendar:fictional:2030-2032'
        self.store.ingest(batch)
        self.assertIsNotNone(self.store.get('calendar', self.item('obsolete')['id']))

    def test_missing_guard_preserves_normal_ingestion(self):
        self.store.ingest(self.fresh())
        self.assertIsNotNone(self.store.get('calendar', self.item('obsolete')['id']))

    def test_insecure_or_invalid_guard_fails_closed(self):
        path = self.install()
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'private regular file'):
            self.store.ingest(self.fresh())
        path.chmod(0o600)
        self.guard['expected_id_digest'] = {}
        self.install()
        with self.assertRaisesRegex(ValueError, 'invalid exact'):
            self.store.ingest(self.fresh())
        self.assertIsNotNone(self.store.get('calendar', self.item('obsolete')['id']))

    def test_other_source_is_unaffected(self):
        self.install()
        batch = self.fresh()
        batch['source'] = 'apple-local'
        self.store.ingest(batch)
        self.assertIsNotNone(self.store.get('calendar', self.item('obsolete')['id']))
