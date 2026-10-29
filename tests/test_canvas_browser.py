import ctypes
import ctypes.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import httpx
from personal_context.canvas_browser import BrowserCanvasClient, session_cookies, private_read, run

class BrowserTests(unittest.TestCase):
    def session(self, path):
        raw=json.dumps({'cookies':[{'host':'school.example.invalid','name':'session','value':'fictional','originAttributes':{'userContextId':0,'privateBrowsingId':0,'partitionKey':''}},
                                  {'host':'.other.example.invalid','name':'private','value':'never-transfer'}]}).encode()
        lib=ctypes.CDLL(ctypes.util.find_library('lz4'))
        out=ctypes.create_string_buffer(len(raw)*2+100)
        size=lib.LZ4_compress_default(raw,out,len(raw),len(out))
        path.write_bytes(b'mozLz40\0'+struct.pack('<I',len(raw))+out.raw[:size]);path.chmod(0o600)

    def test_session_reads_only_exact_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'session';self.session(path)
            cookies=session_cookies(path,'school.example.invalid')
            self.assertEqual(list(cookies),['session'])
            with self.assertRaises(PermissionError):session_cookies(path,'absent.example.invalid')
            with self.assertRaises(PermissionError):session_cookies(Path(tmp)/'missing','school.example.invalid')
            path.chmod(0o644)
            with self.assertRaises(ValueError):session_cookies(path,'school.example.invalid')

    def test_symlink_and_decompression_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'session';self.session(path)
            link=Path(tmp)/'link';link.symlink_to(path)
            with self.assertRaises(OSError):private_read(link)
            path.write_bytes(b'mozLz40\0'+struct.pack('<I',2**31)+b'invalid')
            with self.assertRaises(ValueError):session_cookies(path,'school.example.invalid')

    def client(self, handler):
        cookies=httpx.Cookies();cookies.set('session','fictional',domain='school.example.invalid')
        return BrowserCanvasClient('https://school.example.invalid',cookies,transport=httpx.MockTransport(handler))

    def test_read_auth_and_pagination(self):
        def handler(request):
            self.assertEqual(request.method,'GET');self.assertNotIn('authorization',request.headers)
            self.assertIn('session=fictional',request.headers['cookie'])
            if request.url.params.get('page')=='2':return httpx.Response(200,json=[{'id':2}])
            return httpx.Response(200,json=[{'id':1}],headers={'link':'</api/v1/courses?page=2>; rel="next"'})
        client=self.client(handler)
        self.assertEqual(len(client.pages('/api/v1/courses')),2);client.close()

    def test_no_writes_external_requests_or_marking_read(self):
        seen=[]
        def handler(request):seen.append(request);return httpx.Response(200,json={})
        client=self.client(handler)
        for path in ('/logout','https://outside.example.invalid/api/v1/courses','/api/v1/conversations/1',
                     '/api/v1/conversations/1?auto_mark_as_read=true','/api/v1/courses?_method=POST',
                     '/api/v1/conversations/1?auto_mark_as_read=false&auto_mark_as_read=true'):
            with self.assertRaises(ValueError):client.get(path)
        with self.assertRaises(ValueError):client.http.post('https://school.example.invalid/api/v1/courses')
        self.assertEqual(seen,[])
        self.assertEqual(client.get('/api/v1/conversations/1?auto_mark_as_read=false'),{})
        client.close()

    def test_wrong_user_never_collects_or_ingests(self):
        with tempfile.TemporaryDirectory() as tmp:
            config={'account':'demo','base_url':'https://school.example.invalid','expected_user_id':7,
                    'session_file':tmp+'/session','status_file':tmp+'/status'}
            path=Path(tmp)/'config';path.write_text(json.dumps(config));path.chmod(0o600)
            with patch('personal_context.canvas_browser.session_cookies',return_value=httpx.Cookies()), \
                 patch('personal_context.canvas_browser.BrowserCanvasClient') as factory, \
                 patch('personal_context.canvas_browser.collect_batches') as collect, \
                 patch('personal_context.canvas_browser.Store') as store:
                factory.return_value.pacer.requests_started=1
                factory.return_value.get.return_value={'id':8}
                result=run(path,tmp+'/db')
                self.assertEqual(result['state'],'authentication_required')
                collect.assert_not_called();store.assert_not_called()

    def test_auth_expiry_preserves_last_success(self):
        from personal_context.canvas_modules import CanvasAPIError
        with tempfile.TemporaryDirectory() as tmp:
            config={'account':'demo','base_url':'https://school.example.invalid','expected_user_id':7,
                    'session_file':tmp+'/session','status_file':tmp+'/status'}
            path=Path(tmp)/'config';path.write_text(json.dumps(config));path.chmod(0o600)
            status=Path(tmp)/'status';status.write_text(json.dumps({'last_success_at':'prior','counts':{'canvas_course':2}}));status.chmod(0o600)
            with patch('personal_context.canvas_browser.session_cookies',return_value=httpx.Cookies()),patch('personal_context.canvas_browser.BrowserCanvasClient') as factory,patch('personal_context.canvas_browser.Store') as store:
                factory.return_value.pacer.requests_started=1
                factory.return_value.get.side_effect=CanvasAPIError(401)
                result=run(path,tmp+'/db');store.assert_not_called()
                self.assertEqual(result['last_success_at'],'prior');self.assertEqual(result['counts'],{'canvas_course':2})
                self.assertEqual(result['state'],'authentication_required')

class BrowserParityTests(unittest.TestCase):
    def test_historical_denied_course_is_preserved_with_coverage(self):
        from personal_context.canvas_collect import collect_batches
        requests=[]
        def handler(request):
            requests.append(request)
            path=request.url.path
            if path=='/api/v1/courses':
                self.assertNotIn('enrollment_state',request.url.params)
                return httpx.Response(200,json=[{'id':7,'name':'Completed fictional course'}])
            if path.startswith('/api/v1/courses/7/') or path=='/api/v1/courses/7':return httpx.Response(403,json={})
            return httpx.Response(200,json=[])
        client=BrowserCanvasClient('https://school.example.invalid',httpx.Cookies(),transport=httpx.MockTransport(handler))
        batches=collect_batches(client,'demo',include_inactive=True)
        self.assertEqual(next(b for b in batches if b['kind']=='canvas_course')['records'][0]['title'],'Completed fictional course')
        self.assertFalse(any(b['kind']=='canvas_assignment' for b in batches))
        state=next(b for b in batches if b['kind']=='canvas_collection_state' and b['scope']=='demo:course:7')['records'][0]['payload']
        self.assertEqual(state['features']['assignment']['status'],'unavailable')
        self.assertEqual(state['features']['announcement']['http_status'],403)
        client.close()

    def test_grade_projection_filters_account_and_keeps_ungraded_null(self):
        import os
        from personal_context.store import Store
        from personal_context.canvas_mcp_server import register_tools
        functions={}
        class Registry:
            def tool(self,**kwargs):
                def save(fn):functions[fn.__name__]=fn;return fn
                return save
        with tempfile.TemporaryDirectory() as tmp:
            key=Path(tmp)/'key';key.write_bytes(os.urandom(32));key.chmod(0o600)
            database=Path(tmp)/'db';store=Store(database,key_file=key)
            base={'schema':1,'source':'canvas-lms','complete':True,'collected_at':'2026-01-01T00:00:00Z'}
            for account in ('college','highschool'):
                store.ingest(dict(base,kind='canvas_course',scope=account,records=[{'id':f'canvas:{account}:course:7','title':'Fictional','payload':{'enrollments':[{'computed_current_score':0}]}}]))
            store.ingest(dict(base,kind='canvas_assignment',scope='college:course:7',records=[{'id':'canvas:college:assignment:7:8','title':'Ungraded','payload':{'submission':{'score':None,'grade':None},'points_possible':10}}]))
            store.close()
            with patch.dict(os.environ,{'PERSONAL_CONTEXT_DB':str(database),'PERSONAL_CONTEXT_KEY_FILE':str(key)}):
                register_tools(Registry())
                grades=functions['canvas_grades'](account='college')
                self.assertEqual(grades['total'],1)
                self.assertEqual(grades['results'][0]['enrollments'][0]['computed_current_score'],0)
                grades=functions['canvas_grades'](course_record_id='canvas:college:course:7')
                self.assertIsNone(grades['results'][0]['score'])
                self.assertIn('canvas_browser_status',functions)
                self.assertIn('refresh_canvas_browser',functions)

class BrowserFileTests(unittest.TestCase):
    def test_download_cdn_never_receives_session(self):
        requests=[]
        def handler(request):
            requests.append(request)
            if request.url.host=='school.example.invalid':
                self.assertIn('session=fictional',request.headers.get('cookie',''))
                return httpx.Response(302,headers={'location':'https://content.cluster1.canvas-user-content.com/signed-file'})
            self.assertNotIn('cookie',request.headers);self.assertNotIn('authorization',request.headers)
            if request.url.host.endswith('.canvas-user-content.com'):
                return httpx.Response(302,headers={'location':'https://inst-fs-region.inscloudgate.net/signed-file'})
            return httpx.Response(200,content=b'%PDF-fictional')
        cookies=httpx.Cookies();cookies.set('session','fictional',domain='school.example.invalid')
        client=BrowserCanvasClient('https://school.example.invalid',cookies,transport=httpx.MockTransport(handler))
        self.assertEqual(client.download('/files/123/download'),b'%PDF-fictional')
        self.assertEqual(len(requests),3)
        with self.assertRaises(ValueError):client.download('https://untrusted.example.invalid/private')
        with self.assertRaises(ValueError):client.download('https://school.example.invalid/logout')
        client.close()

    def test_module_file_fallback_is_non_authoritative_and_extracts_slides(self):
        from personal_context.canvas_browser import linked_file_batches
        from unittest.mock import Mock
        import io,zipfile
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('ppt/slides/slide1.xml','<root xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>Fictional slide lesson</a:t></root>')
        client=Mock();client.get.return_value={'id':8,'filename':'lesson.pptx','url':'https://school.example.invalid/files/8/download'}
        client.download.return_value=out.getvalue()
        stamp='2026-01-01T00:00:00Z'
        batches=[{'kind':'canvas_module_item','collected_at':stamp,'records':[{'payload':{'type':'File','course_id':7,'content_id':8}}]},
                 {'kind':'canvas_collection_state','records':[{'payload':{'course_id':7,'features':{'file':{'status':'unavailable'}}}}]}]
        result=linked_file_batches(client,batches,'demo')
        file=next(b for b in result if b['kind']=='canvas_file')
        self.assertFalse(file['complete']);self.assertEqual(file['records'][0]['body'],'Fictional slide lesson')
        self.assertEqual(file['records'][0]['payload']['extraction_status'],'available')
        self.assertEqual(batches[1]['records'][0]['payload']['features']['file']['status'],'unavailable')
        self.assertEqual(batches[1]['records'][0]['payload']['features']['module_linked_file']['available_count'],1)

class FileBoundTests(unittest.TestCase):
    def test_textbook_size_is_bounded_at_64_mib(self):
        from personal_context.canvas_pdf import MAX_FILE_BYTES, _write_pdf
        self.assertEqual(MAX_FILE_BYTES,64*1024*1024)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):_write_pdf(tmp,b'%PDF-'+bytes(MAX_FILE_BYTES))


class BrowserRefreshTests(unittest.TestCase):
    def test_held_lock_does_not_launch_second_collector(self):
        import fcntl
        from personal_context.canvas_browser_mcp import refresh_canvas_browser
        with tempfile.TemporaryDirectory() as tmp:
            settings={'account':'demo','status_file':tmp+'/status'}
            with open(tmp+'/status.lock','w') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch('personal_context.canvas_browser_mcp.config',return_value=settings), patch('personal_context.canvas_browser_mcp.canvas_browser_status',return_value={}), patch('personal_context.canvas_browser_mcp.subprocess.run') as start:
                    self.assertEqual(refresh_canvas_browser()['state'],'running')
                    start.assert_not_called()
                with patch('personal_context.canvas_browser.load_config',return_value=settings), patch('personal_context.canvas_browser.session_cookies') as cookies:
                    self.assertEqual(run('unused',tmp+'/db')['state'],'running')
                    cookies.assert_not_called()

    def test_account_routing_keeps_mac_separate(self):
        import os
        from personal_context.canvas_mcp_server import register_tools
        functions={}
        class Registry:
            def tool(self,**kwargs):
                def save(fn):functions[fn.__name__]=fn;return fn
                return save
        with patch.dict(os.environ,{'PERSONAL_CONTEXT_REFRESH_ENABLED':'1'}), patch('personal_context.canvas_browser_mcp.config',return_value={'account':'demo'}), patch('personal_context.canvas_browser_mcp.refresh_canvas_browser',autospec=True,return_value={'state':'queued'}) as browser, patch('personal_context.refresh_mcp.request',return_value={'refresh_id':'fictional'}) as mac:
            register_tools(Registry())
            self.assertEqual(functions['force_refresh_canvas'](account='demo')['state'],'queued')
            mac.assert_not_called()
            with self.assertRaises(ValueError):functions['force_refresh_canvas'](account='unknown')
            self.assertEqual(functions['force_refresh_canvas']()['refresh_id'],'fictional')
            browser.assert_called_once()

    def test_login_html_and_redirect_require_interactive_auth(self):
        for status,headers in [(200,{'content-type':'text/html; charset=utf-8'}), (302,{}), (307,{})]:
            client=BrowserCanvasClient('https://school.example.invalid',httpx.Cookies(),
                transport=httpx.MockTransport(lambda request: httpx.Response(status,headers=headers,content=b'login')))
            try:
                with self.assertRaises(PermissionError):client.get('/api/v1/users/self/profile')
            finally:client.close()

    def test_authentication_exit_prevents_service_retry(self):
        from personal_context.canvas_browser import main
        for state,code in [('authentication_required',2),('failed',1)]:
            with patch('sys.argv',['canvas-browser','--config','unused','--db','unused']), patch('personal_context.canvas_browser.run',return_value={'state':state}), patch('builtins.print'):
                with self.assertRaises(SystemExit) as error:main()
                self.assertEqual(error.exception.code,code)


class RequestPacingTests(unittest.TestCase):
    def clock(self):
        self.now = 0.0
        def sleep(delay):self.now += delay
        return patch('personal_context.canvas_browser.time.monotonic',side_effect=lambda:self.now), patch('personal_context.canvas_browser.time.sleep',side_effect=sleep)

    def test_parallel_workers_share_budget_without_burst_credit(self):
        from concurrent.futures import ThreadPoolExecutor
        from personal_context.canvas_browser import RequestPacer
        pacer=RequestPacer(0.54)
        monotonic,sleep=self.clock()
        with monotonic,sleep,ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:pacer.wait(),range(1000)))
            self.assertAlmostEqual(self.now,999*0.54)
            self.assertEqual(pacer.requests_started,1000)
            self.now += 10
            pacer.wait();stamp=self.now;pacer.wait()
            self.assertAlmostEqual(self.now-stamp,0.54)

    def test_api_and_file_redirects_share_same_pacer(self):
        starts=[]
        def handler(request):
            starts.append(self.now)
            if request.url.path.startswith('/api/v1/'):
                return httpx.Response(200,json={'id':7})
            if request.url.host=='school.example.invalid':
                return httpx.Response(302,headers={'location':'https://content.canvas-user-content.com/signed'})
            self.assertNotIn('cookie',request.headers)
            return httpx.Response(200,content=b'%PDF-fictional')
        monotonic,sleep=self.clock()
        client=BrowserCanvasClient('https://school.example.invalid',httpx.Cookies(),transport=httpx.MockTransport(handler),request_interval=0.54)
        with monotonic,sleep:
            client.get('/api/v1/users/self/profile');client.download('/files/7/download')
        client.close()
        self.assertEqual(starts,[0,0.54,1.08])

    def test_throttle_stops_workers_and_preserves_retry_after(self):
        from personal_context.canvas_browser import RequestPacer,CanvasThrottled
        pacer=RequestPacer()
        with patch('personal_context.canvas_browser.time.time',return_value=1000):
            with self.assertRaises(CanvasThrottled) as error:
                pacer.response(httpx.Response(429,headers={'Retry-After':'3600'}))
            self.assertEqual(error.exception.retry_at,4600)
        with self.assertRaises(CanvasThrottled):pacer.wait()
        self.assertEqual(pacer.requests_started,0)

    def test_persisted_cooldown_skips_authentication_and_archive(self):
        from personal_context.canvas_browser import write_status
        with tempfile.TemporaryDirectory() as tmp:
            settings={'account':'demo','status_file':tmp+'/status'}
            write_status(settings['status_file'],{'last_success_at':'prior','state':'rate_limited','retry_not_before_epoch':5000})
            with patch('personal_context.canvas_browser.load_config',return_value=settings), patch('personal_context.canvas_browser.time.time',return_value=1000), patch('personal_context.canvas_browser.session_cookies') as cookies, patch('personal_context.canvas_browser.Store') as store:
                result=run('unused',tmp+'/db')
                self.assertEqual(result['state'],'rate_limited')
                self.assertEqual(result['last_success_at'],'prior')
                cookies.assert_not_called();store.assert_not_called()
