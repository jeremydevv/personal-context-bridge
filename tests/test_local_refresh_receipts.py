"""Invocation receipts use fictional pipeline state and stubbed remote commands."""
from contextlib import redirect_stdout
import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

from personal_context.saved_video import sync_saved

IDENTITY = {'PERSONAL_CONTEXT_REFRESH_ID': 'fictional-refresh',
            'PERSONAL_CONTEXT_REFRESH_ATTEMPT': 'fictional-attempt',
            'PERSONAL_CONTEXT_REFRESH_SOURCE': 'saved_video'}


class SavedReceipts(unittest.TestCase):
    def test_complete_unchanged_partial_and_quiet_receipts(self):
        for previous, collector, expected in (
                ({'processed_allowlist_sha256': 'fictional', 'last_processing_ok': True},
                 {'ok': True, 'allowlist_sha256': 'fictional'}, 'complete'),
                ({'collection_retry_after': 10**12}, {}, 'partial'),
                ({}, {'ok': False, 'reason': 'fixture_failure'}, 'partial')):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                state = Path(tmp) / 'saved-video-sync.json'; state.write_text(json.dumps(previous))
                output = io.StringIO()
                with patch.object(sync_saved, 'STATE', state), patch.dict(os.environ, IDENTITY), patch.object(sync_saved.subprocess, 'run', return_value=types.SimpleNamespace(stdout=json.dumps(collector), returncode=0)), redirect_stdout(output):
                    result = sync_saved.run()
                self.assertIsInstance(result, dict)
                receipt = json.loads(output.getvalue())
                self.assertEqual(receipt['refresh_id'], 'fictional-refresh')
                self.assertEqual(receipt['attempt_id'], 'fictional-attempt')
                self.assertEqual(receipt['coverage'], expected)
                self.assertEqual(receipt['source'], 'saved_video')
                self.assertEqual(receipt['batch_ids'], [])
                self.assertEqual(receipt['acked_batch_ids'], [])
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state.json'; state.write_text(json.dumps({'collection_retry_after':10**12}))
            output = io.StringIO()
            with patch.object(sync_saved, 'STATE', state), patch.dict(os.environ, {key:'' for key in IDENTITY}), redirect_stdout(output):
                sync_saved.run()
            self.assertEqual(output.getvalue(), '')

    def test_actual_processor_report_is_required_and_lock_skip_never_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); state = root / 'state.json'
            def process(command, **kwargs):
                if 'personal_context.saved_video.collect_saved' in command:
                    return types.SimpleNamespace(stdout=json.dumps({'ok':True,'allowlist_sha256':'fictional'}),returncode=0)
                (root / 'run-report.json').write_text(json.dumps({'failed':0,'total':1,'complete':1,'allowlist_sha256':'fictional'}))
                return types.SimpleNamespace(returncode=0)
            output = io.StringIO()
            with patch.object(sync_saved,'STATE',state), patch.object(sync_saved,'DEFAULT_DATA',root), patch.dict(os.environ,IDENTITY), patch.object(sync_saved.subprocess,'run',side_effect=process), redirect_stdout(output):
                sync_saved.run()
            self.assertEqual(json.loads(output.getvalue())['coverage'],'complete')
            with (root / 'saved-video-sync.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                output = io.StringIO()
                with patch.object(sync_saved,'STATE',state), patch.dict(os.environ,IDENTITY), redirect_stdout(output):
                    result = sync_saved.run()
                self.assertNotEqual(result.get('coverage'),'complete')
                self.assertEqual(output.getvalue(),'')

    def test_stale_or_incomplete_processor_reports_never_complete(self):
        for report, rewrite in (({'failed':0,'total':1,'complete':1,'allowlist_sha256':'fictional'},False),
                                ({'failed':0,'total':1,'complete':0,'allowlist_sha256':'fictional'},True)):
            with self.subTest(rewrite=rewrite), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);state=root/'state.json';report_path=root/'run-report.json'
                report_path.write_text(json.dumps(report))
                def process(command, **kwargs):
                    if 'personal_context.saved_video.collect_saved' in command:
                        return types.SimpleNamespace(stdout=json.dumps({'ok':True,'allowlist_sha256':'fictional'}),returncode=0)
                    if rewrite:
                        replacement=root/'replacement.json';replacement.write_text(json.dumps(report));replacement.replace(report_path)
                    return types.SimpleNamespace(returncode=0)
                output=io.StringIO()
                with patch.object(sync_saved,'STATE',state),patch.object(sync_saved,'DEFAULT_DATA',root),patch.dict(os.environ,IDENTITY),patch.object(sync_saved.subprocess,'run',side_effect=process),redirect_stdout(output):
                    sync_saved.run()
                self.assertEqual(json.loads(output.getvalue())['coverage'],'partial')
        with patch.object(sync_saved,'run',return_value={'coverage':'partial'}):
            self.assertIsNone(sync_saved.main())


class ObsidianReceipts(unittest.TestCase):
    def test_exact_invocation_receipt_only_after_successful_real_sync(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/obsidian_icloud_sync.sh'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); binary=root/'bin';binary.mkdir(); vault=root/'vaults'/'DemoVault';(vault/'.obsidian').mkdir(parents=True)
            (vault/'.obsidian/app.json').write_text('{}');(vault/'.RCLONE_TEST').write_text('fictional marker')
            mountpoint=binary/'mountpoint';mountpoint.write_text('#!/bin/sh\nexit 0\n');mountpoint.chmod(0o700)
            rclone=binary/'rclone';rclone.write_text('''#!/bin/sh
if [ "$1" = lsf ]; then case "$2" in */app.json) echo app.json;; *) echo .RCLONE_TEST;; esac; fi
if [ "$1" = bisync ] && [ "${FIXTURE_FAIL:-0}" = 1 ]; then exit 1; fi
exit 0
''');rclone.chmod(0o700)
            env={**os.environ,**IDENTITY,'PERSONAL_CONTEXT_REFRESH_SOURCE':'obsidian',
                 'OBSIDIAN_VAULT_ROOT':str(root/'vaults'),'OBSIDIAN_VAULTS':'DemoVault',
                 'OBSIDIAN_ICLOUD_BASE':'fixture:drive','OBSIDIAN_REMOTE_BACKUP_BASE':'fixture:backup',
                 'RCLONE_BIN':str(rclone),'PATH':str(binary)+':'+os.environ['PATH']}
            success=subprocess.run(['bash',str(script),'--run'],env=env,capture_output=True,text=True)
            self.assertEqual(success.returncode,0,success.stderr)
            receipt=json.loads(success.stdout)
            self.assertEqual(receipt['source'],'obsidian');self.assertEqual(receipt['coverage'],'complete')
            self.assertEqual(receipt['refresh_id'],'fictional-refresh');self.assertEqual(receipt['attempt_id'],'fictional-attempt')
            for mode, extra in (('--run',{'FIXTURE_FAIL':'1'}),('--dry-run',{}),('--run',{'PERSONAL_CONTEXT_REFRESH_ATTEMPT':''})):
                result=subprocess.run(['bash',str(script),mode],env={**env,**extra},capture_output=True,text=True)
                self.assertEqual(result.stdout,'')
