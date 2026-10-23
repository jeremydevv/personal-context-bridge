import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from personal_context.icloud_drive import Drive, DriveError, normalize_path


class DriveTests(unittest.TestCase):
    def test_reject_remote_paths_and_traversal(self):
        for p in ('../x', '/etc/passwd', 'foo/../x', 'other:x', ':local:/tmp', 'foo\\bar', 'x\x00'):
            with self.subTest(p=p), self.assertRaises(ValueError):
                normalize_path(p)
        self.assertEqual(normalize_path('Folder/hello.txt'), 'Folder/hello.txt')

    def test_unconfigured_does_not_run_rclone(self):
        with tempfile.TemporaryDirectory() as d, patch('personal_context.icloud_drive.subprocess.Popen') as popen:
            drive=Drive(root=Path(d))
            self.assertEqual(drive.status()['state'], 'authentication_required')
            with self.assertRaises(DriveError): drive.list('')
            popen.assert_not_called()

    def test_bounds_before_process(self):
        drive=Drive()
        for kwargs in ({'offset':-1}, {'max_bytes':262145}, {'max_bytes':0}):
            with self.assertRaises(ValueError):drive.chunk('file',**kwargs)
        with self.assertRaises(ValueError):drive.list('',limit=1001)
        with self.assertRaises(ValueError):drive.search('',max_depth=11)

    def test_safe_environment(self):
        with patch.dict(os.environ, {'RCLONE_CONFIG_ICLOUD_TYPE':'local','RCLONE_DUMP':'bodies',
                                    'AWS_SECRET_ACCESS_KEY':'secret','PYTHONPATH':'/tmp/evil'}):
            env=Drive().environment()
            self.assertNotIn('RCLONE_DUMP',env)
            self.assertNotIn('RCLONE_CONFIG_ICLOUD_TYPE',env)
            self.assertNotIn('AWS_SECRET_ACCESS_KEY',env)
            self.assertNotIn('PYTHONPATH',env)

    def test_encrypted_config_and_owner_permissions_required(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);root.chmod(0o700)
            conf=root/'rclone.conf';conf.write_text('[icloud]\ntype=local\n');conf.chmod(0o600)
            drive=Drive(root=root)
            with self.assertRaises(DriveError):drive._require_config()
            conf.write_text('RCLONE_ENCRYPT_V0:\nfictional');conf.chmod(0o644)
            with self.assertRaises(DriveError):drive._require_config()
            conf.chmod(0o600);drive._require_config()

    def test_listing_and_search_are_bounded(self):
        drive=Drive()
        rows=[{'Path':'B.txt','Name':'B.txt','Size':3,'IsDir':False},
              {'Path':'A.txt','Name':'A.txt','Size':4,'IsDir':False}]
        with patch.object(drive,'_json',return_value=rows) as call:
            result=drive.list('folder',limit=1)
            self.assertEqual(len(result['items']),1)
            self.assertTrue(result['has_more'])
            self.assertNotIn('--recursive',call.call_args.args[0])
            self.assertEqual(len(drive.search('a.txt')['items']),1)

    def test_chunk_and_text(self):
        drive=Drive()
        with patch.object(drive,'info',return_value={'Size':6,'IsDir':False}), patch.object(drive,'_run',return_value=b'hello!'):
            self.assertEqual(drive.text('hello.txt')['text'],'hello!')
            self.assertEqual(drive.chunk('hello.txt')['next_offset'],6)
            self.assertTrue(drive.chunk('hello.txt')['eof'])
        with self.assertRaises(ValueError):drive.text('program.exe')

    def test_process_errors_redacted(self):
        with tempfile.TemporaryDirectory() as d:
            drive=Drive(root=Path(d))
            with patch.object(drive,'_require_config'),patch('personal_context.icloud_drive.subprocess.Popen') as p:
                p.return_value.stdout.read.return_value=b''
                p.return_value.wait.return_value=1
                with self.assertRaisesRegex(DriveError,'authentication or provider') as err:drive._run(['lsjson','icloud:'])
                self.assertNotIn('secret',str(err.exception))


class ProcessBoundaryTests(unittest.TestCase):
    def test_actual_process_output_cap_timeout_and_error_redaction(self):
        drive=Drive()
        env=drive.environment()
        with self.assertRaisesRegex(DriveError,'safety bound'):
            drive._execute(['/usr/bin/python3','-c','import sys;sys.stdout.write("x"*1000)'],32,5)
        with self.assertRaisesRegex(DriveError,'timed out'):
            drive._execute(['/usr/bin/python3','-c','import time;time.sleep(10)'],32,0.05)
        with self.assertRaisesRegex(DriveError,'authentication or provider') as error:
            drive._execute(['/usr/bin/python3','-c','import sys;print("private-token",file=sys.stderr);sys.exit(1)'],32,5)
        self.assertNotIn('private-token',str(error.exception))

    def test_lock_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            drive=Drive(root=Path(d))
            with drive.lock(),self.assertRaisesRegex(DriveError,'busy'):
                with Drive(root=Path(d)).lock():pass
