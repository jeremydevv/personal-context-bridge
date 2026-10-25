import json
from pathlib import Path
import sys
import tempfile
import unittest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from personal_context.onboarding import initialize

class SourceMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_source_starts_with_writes_and_refresh_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'runtime';initialize(root,demo=True)
            for source in ('calendar','reminder','contact','mail','message','note','voice_memo'):
                server=StdioServerParameters(command=sys.executable,
                    args=['-m','personal_context.source_mcp_server','--source',source],
                    env={'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src'),
                         'PERSONAL_CONTEXT_REFRESH_ENABLED':'0','PERSONAL_CONTEXT_APPLE_WRITE_ENABLED':'0',
                         'PERSONAL_CONTEXT_DB':str(root/'context.sqlite3'),
                         'PERSONAL_CONTEXT_KEY_FILE':str(root/'archive.key'),
                         'PERSONAL_CONTEXT_REFRESH_DIR':str(root/'refresh-state')})
                async with stdio_client(server) as (reader,writer):
                    async with ClientSession(reader,writer) as session:
                        await session.initialize()
                        tools=(await session.list_tools()).tools
                        self.assertTrue(all(tool.annotations.readOnlyHint for tool in tools))
                        self.assertTrue({"data_source_status", "data_refresh_status"}.issubset({tool.name for tool in tools}))
                        result=await session.call_tool('apple_'+source+'_status',{})
                        self.assertFalse(result.isError)

    async def test_obsidian_requires_explicit_vaults_and_denies_disabled_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'DemoVault').mkdir();(root/'DemoVault'/'Example.md').write_text('Fictional content')
            server=StdioServerParameters(command=sys.executable,
                args=['-m','personal_context.obsidian_mcp_server'],env={
                    'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src'),
                    'PERSONAL_CONTEXT_REFRESH_ENABLED':'0',
                    'OBSIDIAN_VAULT_ROOT':str(root),'OBSIDIAN_VAULTS':'DemoVault',
                    'OBSIDIAN_REQUIRE_MOUNT':'0'})
            async with stdio_client(server) as (reader,writer):
                async with ClientSession(reader,writer) as session:
                    await session.initialize()
                    names={tool.name for tool in (await session.list_tools()).tools}
                    self.assertNotIn('force_refresh_obsidian',names)
                    self.assertTrue({'data_source_status','data_refresh_status'}.issubset(names))
                    status=await session.call_tool('data_source_status',{})
                    self.assertFalse(status.isError)
                    result=await session.call_tool('obsidian_read_note',{'path':'Example.md'})
                    self.assertFalse(result.isError)
                    result=await session.call_tool('obsidian_write_note',{'path':'New.md','content':'Example'})
                    self.assertTrue(result.isError)
                    self.assertFalse((root/'DemoVault'/'New.md').exists())
