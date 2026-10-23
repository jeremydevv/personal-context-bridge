import json
from pathlib import Path
import sys
import tempfile
import unittest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from personal_context.onboarding import initialize


class DriveMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_main_catalog_without_authentication(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'runtime';initialize(root)
            env={'PERSONAL_CONTEXT_DB':str(root/'context.sqlite3'),
                 'PERSONAL_CONTEXT_KEY_FILE':str(root/'archive.key'),
                 'PERSONAL_CONTEXT_ICLOUD_DIR':str(root/'icloud')}
            server=StdioServerParameters(command=sys.executable,args=['-m','personal_context.mcp_server'],env=env)
            async with stdio_client(server) as (reader,writer):
                async with ClientSession(reader,writer) as session:
                    await session.initialize()
                    names={t.name:t for t in (await session.list_tools()).tools}
                    for name in ('icloud_drive_status','list_icloud_drive','search_icloud_drive',
                                 'icloud_drive_file_info','read_icloud_drive_text','read_icloud_drive_chunk'):
                        self.assertTrue(names[name].annotations.readOnlyHint)
                    result=await session.call_tool('icloud_drive_status',{})
                    self.assertFalse(result.isError)
                    data=result.structuredContent or json.loads(result.content[0].text)
                    self.assertEqual(data['state'],'authentication_required')
                    result=await session.call_tool('list_icloud_drive',{})
                    self.assertTrue(result.isError)
                    self.assertIn('authentication_required',result.content[0].text)
