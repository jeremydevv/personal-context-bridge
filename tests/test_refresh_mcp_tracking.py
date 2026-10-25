"""Fictional MCP refresh contract; no provider or native dispatch."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


class Registry:
    def __init__(self):
        self.tools = {}
    def tool(self, name=None, **kwargs):
        def register(function):
            key = name or function.__name__
            if key in self.tools:
                raise AssertionError('duplicate tool registration: ' + key)
            self.tools[key] = (function, kwargs['annotations'])
            return function
        return register


class RefreshMcpContract(unittest.TestCase):
    def test_scoped_request_and_status_and_opt_in(self):
        from personal_context.refresh_mcp import register
        tracker = types.ModuleType('personal_context.refresh_tracking')
        tracker.request_refresh = lambda sources, mode='recent': {'refresh_id': 'fixture-run', 'sources': sources, 'mode': mode}
        tracker.refresh_status = lambda refresh_id: {'refresh_id': refresh_id, 'sources': {'mail': {'state': 'queued'}, 'note': {'state': 'queued'}}}
        tracker.source_status = lambda source='all', database=None: {'sources': {source: {'capability': 'unconfigured'}}}
        with patch.dict(sys.modules, {'personal_context.refresh_tracking': tracker}), patch.dict(os.environ, {'PERSONAL_CONTEXT_REFRESH_ENABLED': '1'}):
            registry = Registry()
            register(registry, source='mail')
            request, annotation = registry.tools['request_data_refresh']
            self.assertFalse(annotation.readOnlyHint)
            self.assertEqual(request([], 'recent')['sources'], ['mail'])
            with self.assertRaises(ValueError):
                request(['note'])
            self.assertEqual(set(registry.tools['data_refresh_status'][0]('fixture-run')['sources']), {'mail'})
            with self.assertRaises(ValueError):
                registry.tools['data_source_status'][0]('note')
        with patch.dict(os.environ, {'PERSONAL_CONTEXT_REFRESH_ENABLED': '0'}):
            registry = Registry(); register(registry, source='mail')
            self.assertNotIn('request_data_refresh', registry.tools)
            self.assertTrue(all(annotation.readOnlyHint for _, annotation in registry.tools.values()))

    def test_unavailable_tracking_is_explicit_and_preserves_old_status(self):
        from personal_context.refresh_mcp import with_tracking, status
        tracker = types.ModuleType('personal_context.refresh_tracking')
        def unavailable(*args, **kwargs):
            raise OSError('fictional secret path must not escape')
        tracker.source_status = unavailable
        with patch.dict(sys.modules, {'personal_context.refresh_tracking': tracker}):
            result = with_tracking({'last_synced_at': '2000-01-01T00:00:00Z'}, 'mail')
            self.assertEqual(status('fixture-id')['state'], 'unavailable')
        self.assertEqual(result['last_synced_at'], '2000-01-01T00:00:00Z')
        self.assertEqual(result['data_refresh']['status'], 'unavailable')
        self.assertNotIn('fictional secret', str(result))

    def test_main_registers_common_tools_once_and_scopes_travel_results(self):
        from personal_context import mcp_server
        from personal_context.refresh_mcp import register
        registry = Registry(); registry.run = lambda **kwargs: None
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / 'fixture.key'; key.write_bytes(bytes(32))
            with patch.dict(os.environ, {'PERSONAL_CONTEXT_DB': str(Path(tmp) / 'archive'),
                                         'PERSONAL_CONTEXT_KEY_FILE': str(key),
                                         'PERSONAL_CONTEXT_REFRESH_ENABLED': '1',
                                         'PERSONAL_CONTEXT_LOCATION_ENABLED': '1',
                                         'PERSONAL_CONTEXT_SAVED_VIDEO_ENABLED': '1'}), patch('mcp.server.fastmcp.FastMCP', return_value=registry):
                mcp_server.run()
        self.assertTrue({'request_data_refresh', 'data_refresh_status', 'data_source_status'}.issubset(registry.tools))
        tracker = types.ModuleType('personal_context.refresh_tracking')
        tracker.source_status = lambda source='all', database=None: {'configured':True, 'sources':{source:{'capability':'unconfigured'}}}
        tracker.refresh_status = lambda refresh_id: {'refresh_id': refresh_id, 'state': 'running', 'sources': {
            'location': {'state': 'failed'}, 'google_timeline': {'state': 'failed'}, 'mail': {'state': 'running'}}}
        registry = Registry()
        with patch.dict(sys.modules, {'personal_context.refresh_tracking': tracker}):
            register(registry, 'location', allowed_sources=('location', 'google_timeline'))
            result = registry.tools['data_refresh_status'][0]('fixture')
            self.assertTrue(registry.tools['data_source_status'][0]()['configured'])
        self.assertEqual(set(result['sources']), {'location', 'google_timeline'})
        self.assertEqual(result['state'], 'failed')

    def test_shared_source_registrations_discover_read_tools_without_key(self):
        from personal_context import canvas_mcp_server, icloud_drive_mcp, location_mcp, saved_video_mcp, voice_memos_mcp
        from personal_context.service import QueryService
        for module, source in ((canvas_mcp_server, 'canvas'), (icloud_drive_mcp, 'icloud_drive'),
                               (location_mcp, 'location'), (saved_video_mcp, 'saved_video'),
                               (voice_memos_mcp, 'voice_memo')):
            with self.subTest(source=source), patch.dict(os.environ, {'PERSONAL_CONTEXT_REFRESH_ENABLED': '0',
                                                                     'PERSONAL_CONTEXT_LOCATION_ENABLED': '1'}):
                registry = Registry()
                if source == 'canvas': module.register_tools(registry)
                elif source == 'voice_memo': module.register(registry, QueryService('/fictional/unopened'))
                else: module.register(registry)
                self.assertNotIn('request_data_refresh', registry.tools)
                self.assertIn('data_source_status', registry.tools)
                result = registry.tools['data_source_status'][0]()
                self.assertEqual(set(result['sources']), {source})


class RefreshMcpProtocol(unittest.IsolatedAsyncioTestCase):
    async def test_common_status_on_actual_encrypted_source_stdio(self):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
        from personal_context.onboarding import initialize
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'fictional'; initialize(root, demo=True)
            server = StdioServerParameters(command=sys.executable,
                args=['-m', 'personal_context.source_mcp_server', '--source', 'mail'],
                env={'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                     'PERSONAL_CONTEXT_DB': str(root / 'context.sqlite3'),
                     'PERSONAL_CONTEXT_KEY_FILE': str(root / 'archive.key'),
                     'PERSONAL_CONTEXT_REFRESH_DIR': str(root / 'refresh-state')})
            async with stdio_client(server) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                    self.assertIn('data_source_status', tools)
                    self.assertIn('data_refresh_status', tools)
                    self.assertNotIn('request_data_refresh', tools)
                    self.assertTrue(tools['data_source_status'].annotations.readOnlyHint)
                    result = await session.call_tool('data_source_status', {})
                    self.assertFalse(result.isError)
                    result = await session.call_tool('apple_mail_status', {})
                    self.assertFalse(result.isError)
                    self.assertIn('data_refresh', str(result.structuredContent or result.content))
                    result = await session.call_tool('data_source_status', {'source': 'note'})
                    self.assertTrue(result.isError)

    async def test_legacy_wrappers_return_durable_source_only_ids(self):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
        from personal_context.onboarding import initialize
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'fictional'; initialize(root, demo=True)
            config = root / 'refresh.json'
            config.write_text(json.dumps({'sources': {'mail': {'enabled': True, 'capability': 'unconfigured'}, 'note': {'enabled': True, 'capability': 'unconfigured'}}}))
            config.chmod(0o600)
            base = {'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                    'PERSONAL_CONTEXT_DB': str(root / 'context.sqlite3'),
                    'PERSONAL_CONTEXT_KEY_FILE': str(root / 'archive.key'),
                    'PERSONAL_CONTEXT_REFRESH_CONFIG': str(config),
                    'PERSONAL_CONTEXT_REFRESH_DIR': str(root / 'refresh-state'),
                    'PERSONAL_CONTEXT_REFRESH_ENABLED': '1'}
            cases = [(['-m', 'personal_context.source_mcp_server', '--source', source], tool, {source})
                     for source, tool in (('calendar', 'force_refresh_apple_calendar'), ('reminder', 'force_refresh_apple_reminders'),
                                          ('contact', 'force_refresh_apple_contacts'), ('mail', 'force_refresh_apple_mail'),
                                          ('message', 'force_refresh_apple_messages'), ('note', 'force_refresh_apple_notes'),
                                          ('voice_memo', 'force_refresh_apple_voice_memos'))]
            cases.extend([(['-m', 'personal_context.canvas_mcp_server'], 'force_refresh_canvas', {'canvas'}),
                          (['-m', 'personal_context.mcp_server'], 'force_refresh_personal_context', {'mail', 'note'})])
            for args, tool, expected in cases:
                async with stdio_client(StdioServerParameters(command=sys.executable, args=args, env=base)) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        tools = {item.name: item for item in (await session.list_tools()).tools}
                        self.assertFalse(tools['request_data_refresh'].annotations.readOnlyHint)
                        result = await session.call_tool(tool, {})
                        self.assertFalse(result.isError)
                        payload = result.structuredContent or json.loads(result.content[0].text)
                        self.assertTrue(payload['refresh_id'])
                        self.assertEqual(set(payload['sources']), expected)
                        self.assertNotEqual(payload['state'], 'complete')
                        checked = await session.call_tool('data_refresh_status', {'refresh_id': payload['refresh_id']})
                        self.assertFalse(checked.isError)
                        if len(expected) == 1:
                            forbidden = 'mail' if expected == {'note'} else 'note'
                            denied = await session.call_tool('request_data_refresh', {'sources': [forbidden]})
                            self.assertTrue(denied.isError)
                            name = next(iter(expected))
                            if name == 'canvas':
                                compatibility = await session.call_tool('get_canvas_record', {'kind':'data_refresh_status','record_id':payload['refresh_id']})
                            else:
                                compatibility = await session.call_tool('get_apple_' + name + '_record', {'record_id': 'data_refresh_status:' + payload['refresh_id']})
                        else:
                            compatibility = await session.call_tool('get_personal_record', {'kind': 'data_refresh_status', 'record_id': payload['refresh_id']})
                        self.assertFalse(compatibility.isError)

    async def test_standalone_canvas_obsidian_saved_video_status(self):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'DemoVault').mkdir()
            for module, expected in (('personal_context.canvas_mcp_server', 'canvas'),
                                     ('personal_context.obsidian_mcp_server', 'obsidian'),
                                     ('personal_context.saved_video.mcp_server', 'saved_video')):
                env = {'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                       'PERSONAL_CONTEXT_REFRESH_ENABLED': '0',
                       'OBSIDIAN_VAULT_ROOT': str(root), 'OBSIDIAN_VAULTS': 'DemoVault',
                       'OBSIDIAN_REQUIRE_MOUNT': '0'}
                async with stdio_client(StdioServerParameters(command=sys.executable, args=['-m', module], env=env)) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        names = {item.name for item in (await session.list_tools()).tools}
                        self.assertTrue({'data_source_status', 'data_refresh_status'}.issubset(names))
                        self.assertNotIn('request_data_refresh', names)
                        result = await session.call_tool('data_source_status', {})
                        self.assertFalse(result.isError)
                        payload = result.structuredContent or json.loads(result.content[0].text)
                        self.assertEqual(set(payload['sources']), {expected})
