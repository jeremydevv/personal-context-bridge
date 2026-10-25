import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from personal_context.mac_app_lifecycle import collected_app

class LifecycleReceiptTests(unittest.TestCase):
    def exercise(self, initial=False, preserved=False, fail=False):
        state={'running':initial};calls=[]
        def run(args,**kwargs):
            calls.append(args)
            if args[0]=='/usr/bin/open': state['running']=True;out=''
            elif 'quit()' in args[-1]:
                state['running']=preserved
                out=json.dumps({'final_running':preserved,'cleanup':'preserved_for_user' if preserved else 'closed'})
            else:out=str(state['running']).lower()
            return subprocess.CompletedProcess(args,0,out,'')
        with tempfile.TemporaryDirectory() as root,patch.dict('os.environ',{'PERSONAL_CONTEXT_DATA_DIR':root}),patch('personal_context.mac_app_lifecycle.subprocess.run',side_effect=run),patch('personal_context.mail_collect.wait_for_mail_idle'):
            if fail:
                with self.assertRaisesRegex(RuntimeError,'fixture'):
                    with collected_app('Mail') as receipt:raise RuntimeError('fixture')
            else:
                with collected_app('Mail') as receipt:pass
        return receipt,calls
    def test_initially_running_preserved(self):
        receipt,calls=self.exercise(initial=True)
        self.assertEqual(receipt['cleanup'],'preserved_initial')
        self.assertFalse(receipt['launched_by_collector'])
        self.assertFalse(any('quit()' in c[-1] for c in calls))
    def test_collector_owned_closed(self):
        receipt,_=self.exercise()
        self.assertTrue(receipt['launched_by_collector'])
        self.assertEqual(receipt['cleanup'],'closed')
        self.assertFalse(receipt['final_running'])
    def test_user_foreground_or_composition_preserved(self):
        receipt,calls=self.exercise(preserved=True)
        self.assertEqual(receipt['cleanup'],'preserved_for_user')
        self.assertTrue(receipt['final_running'])
        script=next(c[-1] for c in calls if 'quit()' in c[-1])
        self.assertIn('frontmost()',script)
        self.assertIn('outgoingMessages()',script)
    def test_collection_error_still_closes_owned_app(self):
        receipt,_=self.exercise(fail=True)
        self.assertEqual(receipt['cleanup'],'closed')
