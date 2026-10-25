import gzip
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from personal_context.headless_collect import configure_headless, adapter_options
from personal_context.notes_database import consistent_snapshot, decode_note_text, database_snapshot
from personal_context.provider_mail import provider_mail_batches


def field(number, data):
    assert len(data) < 128
    return bytes([number * 8 + 2, len(data)]) + data


class HeadlessTests(unittest.TestCase):
    def tearDown(self):
        configure_headless({})

    def test_adapter_selection_is_explicit_and_resettable(self):
        configure_headless({'headless': {'contacts': {'mode': 'native', 'helper': '/fiction/helper'}}})
        self.assertEqual(adapter_options('contacts')['mode'], 'native')
        configure_headless({})
        self.assertEqual(adapter_options('contacts')['mode'], 'legacy')
        with self.assertRaises(ValueError):
            configure_headless({'headless': {'notes': {'mode': 'guess'}}})

    def test_native_permission_failure_never_runs_gui(self):
        from personal_context.contacts_collect import collect_contacts_snapshot
        configure_headless({'headless': {'contacts': {'mode': 'native', 'helper': '/fiction/helper'}}})
        with patch('personal_context.contacts_collect.subprocess.run') as run:
            run.return_value.returncode = 3
            with self.assertRaises(RuntimeError):
                collect_contacts_snapshot()
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0], ['/fiction/helper'])

    def test_notes_protobuf_and_unsupported_schema(self):
        encoded = gzip.compress(field(2, bytes([16, 1]) + field(3, field(2, b'Fictional note'))))
        self.assertEqual(decode_note_text(encoded), 'Fictional note')
        with self.assertRaises(ValueError):
            decode_note_text(gzip.compress(field(2, b'unknown')))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'notes.db'
            sqlite3.connect(path).close()
            with consistent_snapshot(path) as snapshot:
                with self.assertRaises(ValueError):
                    database_snapshot(snapshot)

    def test_snapshot_includes_committed_wal_and_is_private_and_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'notes.db'
            live = sqlite3.connect(path)
            live.execute('pragma journal_mode=wal')
            live.execute('create table fictional (value text)')
            live.execute("insert into fictional values ('first')")
            live.commit()
            with consistent_snapshot(path) as snapshot:
                self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
                live.execute("insert into fictional values ('later')")
                live.commit()
                with sqlite3.connect(snapshot) as frozen:
                    self.assertEqual(frozen.execute('select count(*) from fictional').fetchone()[0], 1)
            self.assertFalse(snapshot.exists())
            self.assertEqual(live.execute('select count(*) from fictional').fetchone()[0], 2)
            live.close()

    def test_provider_rejects_missing_mapping_and_public_credentials_before_network(self):
        with patch('personal_context.provider_mail.imaplib.IMAP4_SSL') as connect:
            with self.assertRaises(ValueError):
                list(provider_mail_batches({}, '2026-10-25T12:00:00Z'))
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'credential.json'
                path.write_text(json.dumps({'username': 'fiction@example.invalid', 'password': 'fiction'}))
                path.chmod(0o644)
                config = {'mailbox_urls': ['fiction://inbox'], 'headless': {'mail': {
                    'mode': 'imap', 'identity_migration_acknowledged': True, 'host': 'imap.example.invalid', 'credentials_file': str(path),
                    'mailboxes': [{'name': 'INBOX', 'archive_mailbox_url': 'fiction://inbox'}]}}}
                with self.assertRaises(ValueError):
                    list(provider_mail_batches(config, '2026-10-25T12:00:00Z'))
            connect.assert_not_called()

    def test_provider_uses_readonly_peek_and_distinct_non_tombstoning_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'credential.json'
            path.write_text(json.dumps({'username': 'fiction@example.invalid', 'password': 'fiction'}))
            path.chmod(0o600)
            config = {'mailbox_urls': ['fiction://inbox'], 'headless': {'mail': {
                'mode': 'imap', 'identity_migration_acknowledged': True, 'host': 'imap.example.invalid', 'credentials_file': str(path),
                'mailboxes': [{'name': 'INBOX', 'archive_mailbox_url': 'fiction://inbox'}]}}}
            with patch('personal_context.provider_mail.imaplib.IMAP4_SSL') as connect:
                client = connect.return_value
                client.login.return_value = ('OK', [])
                client.select.return_value = ('OK', [b'1'])
                client.response.return_value = ('UIDVALIDITY', [b'7'])
                client.uid.side_effect = [('OK', [b'42']), ('OK', [(b'1 (UID 42 BODY[] {100}', b'From: fiction@example.invalid\r\nSubject: A fiction\r\n\r\nA body'), b')'])]
                batches = list(provider_mail_batches(config, '2026-10-25T12:00:00Z'))
                client.select.assert_called_once_with('"INBOX"', readonly=True)
                self.assertEqual(client.uid.call_args_list[-1].args, ('FETCH', '42', '(UID BODY.PEEK[])'))
                records = [record for batch in batches for record in batch['records']]
                self.assertEqual(len(records), 1)
                self.assertIn('A body', records[0]['body'])
                self.assertTrue(all(not batch['complete'] for batch in batches))
                self.assertTrue(all(batch['source'] == 'provider-imap' for batch in batches))
                self.assertEqual(records[0]['payload']['providerFreshness'], 'server-read')
                client.logout.assert_called_once()


class CoverageTests(unittest.TestCase):
    def test_native_note_supplement_preserves_identity_and_every_other_field(self):
        from personal_context.contacts_native import supplement_contact_notes
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'contacts.db'
            c = sqlite3.connect(path)
            c.executescript('create table ZABCDRECORD (ZUNIQUEID text,ZNOTE integer); create table ZABCDNOTE (Z_PK integer,ZTEXT text);')
            c.execute('insert into ZABCDRECORD values (?,?)', ('fiction', 1))
            c.execute('insert into ZABCDNOTE values (?,?)', (1, 'A fictional relationship note'))
            c.commit();c.close()
            value = {'contacts': [{'id': 'fiction:ABPerson', 'name': 'Fiction', 'emails': [{'id': 'fiction-id', 'label': 'Email', 'value': 'fiction@example.invalid'}], 'note': ''}]}
            result = supplement_contact_notes(value, [str(path)])
            self.assertEqual(result['contacts'][0]['note'], 'A fictional relationship note')
            self.assertEqual(result['contacts'][0]['id'], 'fiction:ABPerson')
            self.assertEqual(result['contacts'][0]['emails'][0]['value'], 'fiction@example.invalid')
            with self.assertRaises(ValueError):
                supplement_contact_notes({'contacts': [{'id': 'absent:ABPerson'}]}, [str(path)])

    def test_notes_fixture_preserves_coredata_identity_dates_and_placeholder_scope(self):
        import plistlib
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'notes.db'
            c = sqlite3.connect(path)
            c.executescript('''create table ZICCLOUDSYNCINGOBJECT (Z_PK integer,Z_ENT integer,ZFOLDER integer,ZNOTEDATA integer,ZTITLE1 text,ZTITLE2 text,ZMARKEDFORDELETION integer,ZISPASSWORDPROTECTED integer,ZCREATIONDATE3 real,ZMODIFICATIONDATE1 real,ZNEEDSINITIALFETCHFROMCLOUD integer);
                create table Z_PRIMARYKEY (Z_NAME text,Z_ENT integer);
                create table Z_METADATA (Z_UUID text,Z_PLIST blob);
                create table ZICNOTEDATA (Z_PK integer,ZDATA blob);''')
            c.executemany('insert into Z_PRIMARYKEY values (?,?)', [('ICNote',1),('ICFolder',2)])
            c.execute('insert into Z_METADATA values (?,?)', ('00000000-0000-0000-0000-000000000000',plistlib.dumps({})))
            c.execute('insert into ZICCLOUDSYNCINGOBJECT (Z_PK,Z_ENT,ZTITLE2) values (2,2,?)', ('Fictional Folder',))
            c.execute('insert into ZICCLOUDSYNCINGOBJECT values (3,1,2,4,?,NULL,0,0,1.75,2.125,0)', ('Fiction',))
            c.execute('insert into ZICCLOUDSYNCINGOBJECT values (5,1,NULL,NULL,NULL,NULL,0,0,NULL,NULL,1)')
            c.execute('insert into ZICNOTEDATA values (4,?)', (gzip.compress(field(2, bytes([16,0])+field(3,field(2,b'Fictional body')))),))
            c.commit();c.close()
            with consistent_snapshot(path) as snapshot:
                value = database_snapshot(snapshot)
            self.assertEqual(value['count'],1)
            self.assertEqual(value['notes'][0]['id'],'x-coredata://00000000-0000-0000-0000-000000000000/ICNote/p3')
            self.assertEqual(value['notes'][0]['createdAt'],'2001-01-01T00:00:01.000Z')
            self.assertEqual(value['notes'][0]['body'],'Fictional body')

    def test_provider_requires_explicit_identity_acknowledgement(self):
        with patch('personal_context.provider_mail.imaplib.IMAP4_SSL') as network:
            with self.assertRaisesRegex(ValueError,'identity_migration_acknowledged'):
                list(provider_mail_batches({'headless':{'mail':{'mode':'imap'}}}, 'fiction'))
            network.assert_not_called()

    def test_provider_profiles_oauth_and_empty_mailboxes_do_not_expand_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            profiles=[]
            for number in range(2):
                path=Path(temporary)/f'credential-{number}.json'
                path.write_text(json.dumps({'username':f'fiction{number}@example.invalid','access_token':'fiction-token'}));path.chmod(0o600)
                profiles.append({'host':'imap.example.invalid','credentials_file':str(path),'mailboxes':[{'name':'INBOX','archive_mailbox_url':f'fiction://{number}'}]})
            config={'mailbox_urls':['fiction://0','fiction://1'],'headless':{'mail':{'mode':'imap','identity_migration_acknowledged':True,'profiles':profiles}}}
            with patch('personal_context.provider_mail.imaplib.IMAP4_SSL') as connect:
                client=connect.return_value;client.authenticate.return_value=('OK',[]);client.select.return_value=('OK',[b'0']);client.response.return_value=('UIDVALIDITY',[b'7']);client.uid.return_value=('OK',[b''])
                batches=list(provider_mail_batches(config,'2026-10-25T12:00:00Z'))
                self.assertEqual(len(batches),2);self.assertTrue(all(not batch['complete'] for batch in batches))
                self.assertEqual(connect.call_count,2);client.login.assert_not_called()
                self.assertEqual(client.authenticate.call_args.args[0],'XOAUTH2')
                self.assertIn(b'auth=Bearer fiction-token',client.authenticate.call_args.args[1](b''))
                self.assertEqual(client.authenticate.call_args.args[1](b'error challenge'),b'')
            config['mailbox_urls'].append('fiction://unmapped')
            with patch('personal_context.provider_mail.imaplib.IMAP4_SSL') as connect:
                with self.assertRaises(ValueError): list(provider_mail_batches(config,'fiction'))
                connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
