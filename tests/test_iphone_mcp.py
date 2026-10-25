import os
import json
from pathlib import Path
import sys
import tempfile
import unittest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from personal_context.onboarding import initialize

class IphoneMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_archives_have_read_only_health_and_travel_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'runtime'
            initialize(root, iphone=True)
            for source, status, count in (('health','apple_health_status','sample_count'), ('travel','iphone_travel_status','location_count')):
                server = StdioServerParameters(command=sys.executable,
                    args=['-m','iphone_context.read_mcp','--source',source],
                    env={'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src'),
                         'PERSONAL_CONTEXT_REFRESH_ENABLED':'0',
                         'IPHONE_' + source.upper() + '_DB':str(root / (source + '.sqlite3')),
                         'IPHONE_ARCHIVE_KEY_FILE':str(root / 'archive.key')})
                async with stdio_client(server) as (reader,writer):
                    async with ClientSession(reader,writer) as session:
                        await session.initialize()
                        tools = (await session.list_tools()).tools
                        self.assertTrue(all(tool.annotations.readOnlyHint for tool in tools))
                        self.assertTrue({"data_source_status", "data_refresh_status"}.issubset({tool.name for tool in tools}))
                        tracking = await session.call_tool("data_source_status", {})
                        self.assertFalse(tracking.isError)
                        result = await session.call_tool(status,{})
                        self.assertFalse(result.isError)
                        payload = result.structuredContent or json.loads(result.content[0].text)
                        self.assertEqual(payload[count],0)
            self.assertEqual((root / 'health.token').stat().st_mode & 0o777,0o600)
            self.assertNotEqual((root / 'health.token').read_text(),(root / 'owntracks.password').read_text())
