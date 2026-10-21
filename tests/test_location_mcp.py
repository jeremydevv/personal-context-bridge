import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from personal_context.onboarding import initialize
from personal_context.subscription_auth import PrivateState
from personal_context.location_dictionary import LocationDictionary

class LocationMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_protocol_dictionary_and_compatibility(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'runtime';initialize(root,iphone=True)
            state=PrivateState(root/'enrichment',(root/'archive.key').read_bytes())
            dictionary=LocationDictionary(state)
            dictionary.update([{'id':'fixture1','timestamp':1000,'latitude':40.,'longitude':-75.,'accuracy_m':5},
                               {'id':'fixture2','timestamp':1600,'latitude':40.,'longitude':-75.,'accuracy_m':5}])
            p=dictionary.search()['places'][0];dictionary.correct(p['place_id'],title='Fictional Library')
            env={'PERSONAL_CONTEXT_DB':str(root/'context.sqlite3'),'PERSONAL_CONTEXT_KEY_FILE':str(root/'archive.key'),
                 'PERSONAL_CONTEXT_LOCATION_ENABLED':'1','PERSONAL_CONTEXT_ENRICHMENT_DIR':str(root/'enrichment')}
            server=StdioServerParameters(command=sys.executable,args=['-m','personal_context.mcp_server'],env=env)
            async with stdio_client(server) as (reader,writer):
                async with ClientSession(reader,writer) as session:
                    await session.initialize();catalog=(await session.list_tools()).tools
                    names={t.name:t for t in catalog}
                    self.assertTrue(names['search_visited_places'].annotations.readOnlyHint)
                    result=await session.call_tool('search_visited_places',{'query':'Library'})
                    self.assertFalse(result.isError)
                    data=result.structuredContent or json.loads(result.content[0].text)
                    self.assertEqual(data['places'][0]['title'],'Fictional Library')
                    self.assertNotIn('latitude',data['places'][0])
                    result=await session.call_tool('get_personal_record',{'kind':'visited_place','record_id':p['place_id']})
                    self.assertFalse(result.isError)
