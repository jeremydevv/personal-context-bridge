import base64
import os
from pathlib import Path
import tempfile
import unittest
from personal_context.icloud_native import NativeDrive, NativeTags, NativeError


class FixtureTags:
    def __init__(self): self.values={}; self.unknown=set()
    def __call__(self, fd):
        key=os.fstat(fd).st_ino
        if key in self.unknown: raise NativeError('access_denied')
        return self.values.get(key,[]).copy()
    def set(self, fd, values): self.values[os.fstat(fd).st_ino]=values.copy()
    def tag(self, p, values): self.values[p.stat().st_ino]=values


class NativeDriveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.tags=FixtureTags()
        (self.root/'Work').mkdir();(self.root/'Personal').mkdir()
        self.old=self.root/'Work/old.txt';self.old.write_text('old')
        self.new=self.root/'Work/new.md';self.new.write_text('new')
        os.utime(self.old,(1000000000,1000000000));os.utime(self.new,(1700000000,1700000000))
        self.tags.tag(self.old,['School']);self.tags.tag(self.new,['School','Project'])
        self.drive=NativeDrive(self.root,{'drive':'','work':'Work'},tags=self.tags,writer=True,protected_tags=['Restricted'])
    def call(self,operation,**kw): return self.drive.dispatch(dict(operation=operation,**kw))
    def test_protection_policy_is_required_and_not_request_controlled(self):
        for policy in (None, [], '', [' '], 'Restricted'):
            with self.subTest(policy=policy),self.assertRaises(ValueError):
                NativeDrive(self.root,tags=self.tags,protected_tags=policy)
        drive=NativeDrive(self.root,tags=self.tags,writer=True,protected_tags=['Restricted','Confidential'])
        item=drive.dispatch({'operation':'info','path':'Work/new.md'})
        with self.assertRaises(ValueError):
            drive.dispatch({'operation':'tag','path':item['path'],'revision':item['revision'],
                            'remove':['  ＣＯＮＦＩＤＥＮＴＩＡＬ  ']})
        out=drive.dispatch({'operation':'tag','path':item['path'],'revision':item['revision'],
                            'add':['Confidential']})
        self.assertTrue(out['now_protected'])
        for operation in ('read','info'):
            with self.assertRaises(NativeError):
                drive.dispatch({'operation':operation,'path':item['path'],'protected_tags':[]})
    def test_filters_scope_and_newest(self):
        r=self.call('search',segment='work',tags=['school'])
        self.assertEqual([x['path'] for x in r['items']],['Work/new.md','Work/old.txt'])
        self.assertEqual(len(self.call('search',segment='work',tags=['project'],name='new',extensions=['md'],modified_after='2020-01-01')['items']),1)
        self.assertEqual(self.call('search',segment='work',folder='Personal')['items'],[])
        with self.assertRaises(NativeError):self.call('info',segment='work',path='Personal')
        with self.assertRaises(ValueError):self.call('search',modified_after='2026-01-01T01:00:00')
    def test_protection_on_all_paths_and_ancestors(self):
        self.tags.tag(self.new,['  RESTRICTED  '])
        self.assertEqual(len(self.call('search')['items']),3) # two folders + old
        for operation in ('info','read','tag','move'):
            with self.subTest(operation=operation),self.assertRaises(NativeError):
                self.call(operation,path='Work/new.md',revision='x',destination='Personal/x.md',add=['a'])
        self.tags.tag(self.root/'Work',['Restricted'])
        self.assertEqual([x['path'] for x in self.call('search')['items']],['Personal'])
        with self.assertRaises(NativeError):self.call('read',path='Work/old.txt')
        with self.assertRaises(NativeError):self.call('mkdir',path='Work/newfolder')
    def test_protected_segment_is_not_disclosed(self):
        self.tags.tag(self.root/'Work',['restricted'])
        self.assertNotIn('work',[x['name'] for x in self.call('segments')['segments']])

    def test_unknown_tags_links_and_special_files(self):
        self.tags.unknown.add(self.old.stat().st_ino)
        (self.root/'link').symlink_to(self.new)
        os.mkfifo(self.root/'fifo')
        paths=[x['path'] for x in self.call('search')['items']]
        self.assertNotIn('Work/old.txt',paths);self.assertNotIn('link',paths);self.assertNotIn('fifo',paths)
        for p in ('Work/old.txt','link','fifo','../secret','/etc/passwd'):
            with self.subTest(p=p),self.assertRaises((NativeError,ValueError)):self.call('read',path=p)
    def test_bounded_read_revision_and_tagging(self):
        item=self.call('info',path='Work/new.md')
        result=self.call('read',path='Work/new.md',revision=item['revision'],max_bytes=2)
        self.assertEqual(base64.b64decode(result['data_base64']),b'ne');self.assertFalse(result['eof'])
        self.new.write_text('changed')
        with self.assertRaises(NativeError):self.call('tag',path='Work/new.md',revision=item['revision'],add=['x'])
        item=self.call('info',path='Work/new.md')
        out=self.call('tag',path=item['path'],revision=item['revision'],add=['Review'],remove=['Project'])
        self.assertEqual(set(out['item']['tags']),{'School','Review'})
        with self.assertRaises(ValueError):self.call('tag',path=item['path'],revision=out['item']['revision'],remove=['restricted'])
    def test_mkdir_move_and_no_delete_or_overwrite(self):
        parent=self.call('info',path='Personal')
        self.call('mkdir',path='Personal/New',revision=parent['revision'])
        with self.assertRaises((NativeError,FileExistsError)):self.call('mkdir',path='Personal/New',revision=self.call('info',path='Personal')['revision'])
        for op in ('delete','remove','upload','copy','execute'):
            with self.assertRaises(ValueError):self.call(op,path='Work/new.md')
        source=self.call('info',path='Work/new.md');dest=self.call('info',path='Personal')
        (self.root/'Personal/exists').write_text('safe')
        with self.assertRaises(NativeError):self.call('move',path=source['path'],revision=source['revision'],destination='Personal/exists',destination_revision=self.call('info',path='Personal')['revision'])
        self.assertEqual((self.root/'Personal/exists').read_text(),'safe');self.assertTrue(self.new.exists())
        # Linux fixture uses the same exclusive kernel primitive as its Darwin counterpart.
        result=self.call('move',path=source['path'],revision=source['revision'],destination='Personal/new.md',destination_revision=self.call('info',path='Personal')['revision'])
        self.assertEqual(result['item']['path'],'Personal/new.md');self.assertFalse(self.new.exists())
    def test_folder_move_protected_child_denied(self):
        self.tags.tag(self.new,['restricted'])
        with self.assertRaises(NativeError):self.call('move',path='Work',revision=self.call('info',path='Work')['revision'],destination='Personal/Work',destination_revision=self.call('info',path='Personal')['revision'])
        self.assertTrue(self.old.exists())
    def test_folder_moves_and_reader_writes_denied(self):
        with self.assertRaises(NativeError):self.call('move',path='Work',revision=self.call('info',path='Work')['revision'],destination='Personal/Work',destination_revision=self.call('info',path='Personal')['revision'])
        reader=NativeDrive(self.root,tags=self.tags,protected_tags=['Restricted'])
        with self.assertRaises(NativeError):reader.dispatch({'operation':'mkdir','path':'new','revision':self.call('info',path='')['revision']})

    def test_replaced_source_cannot_report_successful_file_move(self):
        from unittest.mock import patch
        from personal_context.icloud_native import exclusive_move
        source=self.call('info',path='Work/new.md')
        def replace_then_move(from_fd,name,to_fd,dest):
            os.rename(self.new,self.root/'detached.md')
            self.new.mkdir();child=self.new/'private.txt';child.write_text('fixture')
            self.tags.tag(child,['restricted'])
            exclusive_move(from_fd,name,to_fd,dest)
        with patch('personal_context.icloud_native.exclusive_move',side_effect=replace_then_move):
            with self.assertRaises(NativeError):self.call('move',path=source['path'],revision=source['revision'],destination='Personal/new.md',destination_revision=self.call('info',path='Personal')['revision'])

    def test_scope_paths_limits_and_dates(self):
        for params in ({'limit':1001},{'max_depth':11},{'offset':-1},{'sort':'arbitrary'},{'extensions':['bad/extension']},{'tags':['x']*33}):
            with self.subTest(params=params),self.assertRaises(ValueError):self.call('search',**params)
        with self.assertRaises(ValueError):NativeDrive(self.root,{'bad':'../outside'},tags=self.tags,protected_tags=['Restricted'])
    def test_tag_change_during_read_denied(self):
        original=self.drive._read_bytes
        def changed(fd,offset,count):
            data=original(fd,offset,count);self.tags.tag(self.new,['restricted']);return data
        self.drive._read_bytes=changed
        with self.assertRaises(NativeError):self.call('read',path='Work/new.md')


@unittest.skipUnless(os.uname().sysname=='Darwin','native Finder tags require macOS')
class NativeDarwinTests(NativeDriveTests):
    def setUp(self):
        super().setUp();self.tags=NativeTags();self.drive=NativeDrive(self.root,{'drive':'','work':'Work'},tags=self.tags,writer=True,protected_tags=['Restricted'])
        self.tags.tag=lambda p,t:self.set_native(p,t)
        self.set_native(self.old,['School']);self.set_native(self.new,['School','Project'])
    def set_native(self,p,t):
        fd=os.open(p,os.O_RDONLY)
        try:self.tags.set(fd,t)
        finally:os.close(fd)
    def test_unknown_tags_links_and_special_files(self):
        self.skipTest('fixture injection covered on all platforms')
    def test_foundation_reads_written_tags(self):
        import subprocess
        result=subprocess.run(['swift','-e','import Foundation; print(try URL(fileURLWithPath: CommandLine.arguments[1]).resourceValues(forKeys: [.tagNamesKey]).tagNames!.sorted().joined(separator: ","))',str(self.new)],capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout.strip(),'Project,School')
