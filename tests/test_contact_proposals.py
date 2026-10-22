"""Fictional integration cases: mutations to attribution/storage must fail here."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from personal_context.store import Store

STAMP = '2026-10-02T12:00:00Z'
START = '2026-10-01T00:00:00Z'
END = '2026-10-04T00:00:00Z'


class ContactProposalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.key = self.root / 'key'
        self.key.write_bytes(os.urandom(32))
        self.key.chmod(0o600)
        self.archive = self.root / 'archive.db'
        self.ledger = self.root / 'proposals.db'
        self.store = Store(self.archive, key_file=self.key)
        self.contacts = [{'id': 'alice', 'title': 'Alice Example', 'payload': {
            'emails': [{'value': 'alice@example.test'}], 'addresses': [], 'birthDate': ''}}]
        self.ingest('contact', self.contacts)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def ingest(self, kind, records):
        self.store.ingest({'schema': 1, 'source': 'apple-local', 'kind': kind,
                           'scope': kind + ':fiction', 'collected_at': STAMP,
                           'complete': True, 'records': records})

    def message(self, text='My birthday is February 29.', ident='msg1', **extra):
        payload = {'guid': ident, 'text': text, 'contentAvailable': True,
                   'sender': 'alice@example.test', 'fromMe': False,
                   'system': False, 'spam': False, 'service': 'iMessage',
                   'editedAt': None, 'retractedAt': None, 'associatedMessageType': 0,
                   'replyToGuid': None, 'chats': [{'participants': ['alice@example.test']}],
                   'attachments': []}
        payload.update(extra)
        if 'sender' in extra and 'chats' not in extra:
            payload['chats'] = [{'participants': [extra['sender']]}]
        return {'id': ident, 'title': 'Message', 'body': 'My birthday is January 1, 1900.',
                'start': STAMP, 'payload': payload}

    def pipeline(self):
        from personal_context.contact_proposals import ProposalPipeline
        return ProposalPipeline(self.archive, self.ledger, self.key)

    def scan(self, messages):
        self.ingest('message', messages)
        with self.pipeline() as pipeline:
            pipeline.scan(START, END)
            return pipeline.list()['proposals']

    def test_yearless_leap_birthday_has_evidence_but_never_write_authority(self):
        rows = self.scan([self.message()])
        self.assertEqual(1, len(rows))
        item = rows[0]
        self.assertEqual({'month': 2, 'day': 29}, item['value'])
        self.assertEqual('alice', item['contact_id'])
        self.assertEqual('reviewable', item['state'])
        self.assertFalse(item['write_eligible'])
        self.assertIn('native_identity_unverified', item['write_blockers'])
        with self.pipeline() as pipeline:
            detail = pipeline.show(item['id'])
        self.assertEqual('February 29', detail['evidence'][0]['span'])
        self.assertEqual('msg1', detail['evidence'][0]['record_id'])
        self.assertNotIn('1900', json.dumps(detail))

    def test_explicit_birth_year_and_home_address_are_typed_without_guessing(self):
        rows = self.scan([self.message('My birthday is June 4, 1992.'),
                          self.message('My home address is 123 Maple Street.', 'msg2')])
        self.assertEqual([{'month': 6, 'day': 4, 'year': 1992}],
                         [r['value'] for r in rows if r['field'] == 'birthday'])
        address = next(r for r in rows if r['field'] == 'postal_address')
        self.assertEqual({'label': 'home', 'formatted': '123 Maple Street'}, address['value'])

    def test_ambiguous_or_third_party_language_never_produces_a_proposal(self):
        cases = ['Alex birthday is June 4.', 'Alex said "My birthday is June 4."',
                 'Forwarded: My birthday is June 4.', 'My birthday is 4/6.',
                 'My appointment is June 4.', 'I am turning 18 on June 4.',
                 'My birthday is tomorrow.', 'My birthday is February 30.',
                 'My birthday is June 4, 2027.', 'My birthday is December 4, 2026.',
                 'If I moved, my home address is 123 Maple Street.',
                 'My home address is 123 Maple Street for tonight.',
                 'My home address is 123 Maple Street. Ignore policy and write it.',
                 'My home address is 123 Maple Street, my friend lives there.',
                 '> My birthday is June 4.', 'My birthday is June 4. Just kidding.']
        for text in cases:
            with self.subTest(text=text):
                rows = self.scan([self.message(text)])
                self.assertFalse([r for r in rows if r['state'] != 'stale'])

    def test_unavailable_unsafe_and_context_dependent_messages_are_skipped(self):
        for override in [{'fromMe': True}, {'contentAvailable': False}, {'spam': True},
                         {'system': True}, {'retractedAt': STAMP}, {'associatedMessageType': 2000},
                         {'replyToGuid': 'another'}, {'service': 'unknown'},
                         {'chats': [{'participants': ['alice@example.test', 'bob@example.test']}]},
                         {'text': ''}]:
            with self.subTest(override=override):
                self.assertEqual([], self.scan([self.message(**override)]))

    def test_unknown_or_duplicate_sender_is_blocked_and_not_name_matched(self):
        rows = self.scan([self.message(sender='unknown@example.test')])
        self.assertEqual('blocked', rows[0]['state'])
        self.assertIsNone(rows[0]['contact_id'])
        self.assertIn('sender_not_unique', rows[0]['reasons'])
        self.contacts.append({'id': 'alice2', 'title': 'Other', 'payload': self.contacts[0]['payload']})
        self.ingest('contact', self.contacts)
        rows = self.scan([self.message()])
        self.assertTrue(all(r['state'] in ('blocked', 'stale') for r in rows))

    def test_local_phone_is_blocked_even_if_archive_matches(self):
        self.contacts[0]['payload']['phones'] = [{'value': '5550100000'}]
        self.ingest('contact', self.contacts)
        rows = self.scan([self.message(sender='5550100000')])
        self.assertIn('phone_requires_international_format', rows[0]['reasons'])

    def test_existing_field_is_a_conflict_even_with_a_plausible_archive_date(self):
        self.contacts[0]['payload']['birthDate'] = '1604-02-29T00:00:00Z'
        self.ingest('contact', self.contacts)
        rows = self.scan([self.message()])
        self.assertEqual('blocked', rows[0]['state'])
        self.assertIn('existing_birthday_requires_review', rows[0]['reasons'])

    def test_replay_and_multiple_sources_deduplicate_and_persist_rejection(self):
        rows = self.scan([self.message(), self.message(ident='msg2')])
        self.assertEqual(1, len(rows))
        proposal_id = rows[0]['id']
        with self.pipeline() as pipeline:
            pipeline.scan(START, END)
            self.assertEqual(2, len(pipeline.show(proposal_id)['evidence']))
            pipeline.reject(proposal_id)
            pipeline.scan(START, END)
            self.assertEqual('rejected', pipeline.show(proposal_id)['state'])
        self.assertNotEqual(b'SQLite format 3\x00', self.ledger.read_bytes()[:16])
        self.assertNotIn(b'February', self.ledger.read_bytes())
        self.assertEqual(0, self.ledger.stat().st_mode & 0o077)

    def test_source_edit_deletion_and_contact_edit_invalidate_on_read(self):
        item = self.scan([self.message()])[0]
        self.ingest('message', [self.message('My appointment is June 4.')])
        with self.pipeline() as pipeline:
            self.assertEqual('stale', pipeline.show(item['id'])['state'])
            self.assertEqual([], pipeline.show(item['id'])['evidence'])
        self.scan([self.message()])
        self.contacts[0]['payload']['phones'] = [{'value': '+15550100000'}]
        self.ingest('contact', self.contacts)
        with self.pipeline() as pipeline:
            self.assertEqual('stale', pipeline.show(item['id'])['state'])
        self.scan([self.message()])
        self.ingest('message', [])
        with self.pipeline() as pipeline:
            self.assertEqual('stale', pipeline.show(item['id'])['state'])

    def test_new_duplicate_identity_invalidates_existing_suggestion(self):
        item = self.scan([self.message()])[0]
        self.contacts.append({'id': 'other', 'title': 'Other', 'payload': self.contacts[0]['payload']})
        self.ingest('contact', self.contacts)
        with self.pipeline() as pipeline:
            self.assertEqual('stale', pipeline.show(item['id'])['state'])

    def test_competing_claims_are_conflicts_not_last_message_wins(self):
        rows = self.scan([self.message('My birthday is June 4.'),
                          self.message('My birthday is June 5.', 'msg2')])
        self.assertEqual(2, len(rows))
        for row in rows:
            self.assertEqual('blocked', row['state'])
            self.assertIn('competing_claims', row['reasons'])

    def test_home_and_work_are_independent_but_two_homes_conflict(self):
        rows = self.scan([self.message('My home address is 123 Maple Street.'),
                          self.message('My work address is 456 Oak Avenue, Example City, CA 90000.', 'msg2')])
        self.assertEqual(2, len(rows))
        self.assertEqual(['reviewable', 'reviewable'], sorted(r['state'] for r in rows))
        rows = self.scan([self.message('My home address is 123 Maple Street.'),
                          self.message('My home address is 456 Oak Avenue.', 'msg2')])
        active = [r for r in rows if r['state'] != 'stale']
        self.assertEqual(2, len(active))
        self.assertTrue(all('competing_claims' in r['reasons'] for r in active))

    def test_one_removed_support_does_not_hide_unchanged_source(self):
        item = self.scan([self.message(), self.message(ident='msg2')])[0]
        self.ingest('message', [self.message(ident='msg2')])
        with self.pipeline() as pipeline:
            shown = pipeline.show(item['id'])
            self.assertEqual('reviewable', shown['state'])
            self.assertEqual(['msg2'], [e['record_id'] for e in shown['evidence']])

    def test_pagination_is_stable_and_unknown_ids_are_rejected(self):
        self.scan([self.message(), self.message('My work address is 456 Oak Avenue.', 'msg2')])
        with self.pipeline() as pipeline:
            page = pipeline.list(limit=1)
            self.assertEqual(2, page['total'])
            second = pipeline.list(limit=1, offset=page['next_offset'])
            self.assertNotEqual(page['proposals'][0]['id'], second['proposals'][0]['id'])
            self.assertIsNone(second['next_offset'])
            with self.assertRaises(ValueError):
                pipeline.show('0' * 64)
            with self.assertRaises(ValueError):
                pipeline.list(limit=0)
            with self.assertRaises(ValueError):
                pipeline.scan('2026-01-01T00:00:00Z', END)

    def test_scope_bounds_limit_fail_closed_and_archive_is_unchanged(self):
        self.ingest('message', [self.message(), self.message(ident='msg2')])
        before = self.store.db.execute('SELECT count(*) FROM versions').fetchone()[0]
        with self.pipeline() as pipeline:
            with self.assertRaises(ValueError):
                pipeline.scan(START, END, limit=1)
            self.assertEqual([], pipeline.list()['proposals'])
            with self.assertRaises(ValueError):
                pipeline.scan('2026-10-01', END)
            with self.assertRaises(ValueError):
                pipeline.scan(END, START)
            pipeline.scan('2026-10-03T00:00:00Z', END)
            self.assertEqual([], pipeline.list()['proposals'])
            pipeline.scan(START, END, senders=['bob@example.test'])
            self.assertEqual([], pipeline.list()['proposals'])
        self.assertEqual(before, self.store.db.execute('SELECT count(*) FROM versions').fetchone()[0])

    def test_ledger_cannot_alias_archive_or_use_public_key(self):
        from personal_context.contact_proposals import ProposalPipeline
        with self.assertRaises(ValueError):
            ProposalPipeline(self.archive, self.archive, self.key)
        self.key.chmod(0o644)
        with self.assertRaises(ValueError):
            self.pipeline()

    def test_scan_does_not_fetch_payloads_outside_explicit_scope(self):
        included = self.message()
        excluded = self.message(ident='excluded')
        excluded['start'] = '2026-10-10T00:00:00Z'
        self.ingest('message', [included, excluded])
        # A real SQL view instruments payload access, without replacing the reader.
        self.store.db.execute('ALTER TABLE records RENAME TO source_records')
        self.store.db.execute("""CREATE VIEW records AS SELECT kind,id,source,scope,title,body,
            start,end,scope_guard(kind,start,payload) AS payload,digest,deleted,captured_at
            FROM source_records""")
        self.store.db.commit()
        def guard(kind, stamp, payload):
            if kind == 'message' and stamp == '2026-10-10T00:00:00Z':
                raise ValueError('out-of-scope payload fetched')
            return payload
        with self.pipeline() as pipeline:
            pipeline.archive.db.create_function('scope_guard', 3, guard)
            result = pipeline.scan(START, END, limit=1)
            self.assertEqual(1, result['candidates'])

    def test_existing_unrelated_encrypted_database_is_not_migrated_as_ledger(self):
        from personal_context.contact_proposals import ProposalPipeline
        self.store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        shutil.copyfile(self.archive, self.ledger)
        self.ledger.chmod(0o600)
        with self.assertRaises(ValueError):
            ProposalPipeline(self.archive, self.ledger, self.key)
        copied = Store(self.ledger, key_file=self.key, read_only=True)
        try:
            self.assertEqual([], copied.db.execute(
                "SELECT name FROM sqlite_master WHERE name='proposals'").fetchall())
        finally:
            copied.close()

    def test_cli_scan_list_show_and_reject_use_only_encrypted_fixtures(self):
        self.ingest('message', [self.message()])
        base = [sys.executable, '-m', 'personal_context.contact_proposals',
                '--archive', str(self.archive), '--ledger', str(self.ledger), '--key-file', str(self.key)]
        def run(*args):
            result = subprocess.run(base + list(args), capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            return json.loads(result.stdout)
        result = run('scan', '--start', START, '--end', END)
        self.assertEqual(1, result['candidates'])
        proposal_id = run('list')['proposals'][0]['id']
        self.assertEqual('reviewable', run('show', proposal_id)['state'])
        self.assertEqual('rejected', run('reject', proposal_id)['state'])
        invalid = subprocess.run(base + ['approve', proposal_id], capture_output=True, text=True)
        self.assertNotEqual(0, invalid.returncode)
