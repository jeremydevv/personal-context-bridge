from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
import tempfile
import unittest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from personal_context.onboarding import initialize

class WriteMcpTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def session(self, source='calendar', enabled='1', invalid=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'runtime'; initialize(root,demo=True)
            env={'PERSONAL_CONTEXT_DB':str(root/'context.sqlite3'),'PERSONAL_CONTEXT_KEY_FILE':str(root/'archive.key'),
                 'PERSONAL_CONTEXT_APPLE_WRITE_ENABLED':enabled,'PERSONAL_CONTEXT_APPLE_WRITE_DB':str(root/'writes.db'),
                 'PERSONAL_CONTEXT_APPLE_WRITE_TARGET':'user@mac.example','PERSONAL_CONTEXT_APPLE_WRITE_REMOTE_COMMAND':'/private/bin/receiver'}
            if invalid == 'database': (root/'writes.db').write_bytes(b'not an encrypted database')
            elif invalid: env['PERSONAL_CONTEXT_APPLE_WRITE_REMOTE_COMMAND']='unsafe; shell'
            server=StdioServerParameters(command=sys.executable,args=['-m','personal_context.source_mcp_server','--source',source],env=env)
            async with stdio_client(server) as (reader,writer):
                async with ClientSession(reader,writer) as session:
                    await session.initialize(); yield session

    async def test_write_tools_absent_when_disabled(self):
        async with self.session(enabled='0') as session:
            names={t.name for t in (await session.list_tools()).tools}
            self.assertNotIn('queue_apple_calendar_event',names)
            self.assertIn('search_apple_calendar',names)

    async def test_invalid_queue_config_keeps_read_tools_available(self):
        async with self.session(invalid=True) as session:
            names={t.name for t in (await session.list_tools()).tools}
            self.assertNotIn('queue_apple_calendar_event',names)
            self.assertIn('search_apple_calendar',names)

    async def test_calendar_and_reminder_schemas_are_separate(self):
        for source,expected,absent in [('calendar','queue_apple_calendar_event','queue_apple_reminder'),('reminder','queue_apple_reminder','queue_apple_calendar_event')]:
            async with self.session(source) as session:
                tools={t.name:t for t in (await session.list_tools()).tools}
                self.assertIn(expected,tools); self.assertNotIn(absent,tools)
                self.assertFalse(tools[expected].annotations.readOnlyHint)
                self.assertIn('request_key',tools[expected].inputSchema['required'])

    async def test_queue_status_cancel_tools_report_job_states(self):
        async with self.session() as session:
            result=await session.call_tool('queue_apple_calendar_event',dict(request_key='example',title='Example',start_at='2026-11-01T12:00:00-05:00',end_at='2026-11-01T13:00:00-05:00',notes='private notes'))
            self.assertFalse(result.isError)
            data=json.loads(result.content[0].text); job_id=data['job_id']
            self.assertEqual(set(data),{'job_id','state','created_at'})
            status=await session.call_tool('apple_write_job_status',{'job_id':job_id})
            self.assertEqual(json.loads(status.content[0].text)['state'],'queued')
            pending=await session.call_tool('pending_apple_write_jobs',{})
            self.assertNotIn('private notes',pending.content[0].text)
            cancel=await session.call_tool('cancel_apple_write_job',{'job_id':job_id})
            self.assertEqual(json.loads(cancel.content[0].text)['state'],'cancelled')

    async def test_corrupt_optional_queue_keeps_read_tools_available(self):
        async with self.session(invalid='database') as session:
            names={t.name for t in (await session.list_tools()).tools}
            self.assertIn('search_apple_calendar',names)
            self.assertNotIn('queue_apple_calendar_event',names)

    async def test_structured_edit_tools_queue_without_recreating(self):
        async with self.session() as session:
            tools = {t.name: t for t in (await session.list_tools()).tools}
            self.assertIn('update_apple_calendar_event', tools)
            self.assertTrue(tools['delete_apple_calendar_event'].annotations.destructiveHint)
            self.assertIn('list_apple_calendars', tools)
            self.assertNotIn('update_apple_reminder', tools)
            args = dict(request_key='update', item_id='native-id',
                        occurrence_start_at='2026-11-02T12:00:00-05:00',
                        expected_revision='a' * 64, scope='this', changes={'notes': '', 'location': 'Library'}, automatic_driving=False)
            result = await session.call_tool('update_apple_calendar_event', args)
            self.assertFalse(result.isError, str(result.content))
            self.assertEqual(json.loads(result.content[0].text)['state'], 'queued')
            args['changes'] = {'notes': 'valid field', 'urgent': True}
            invalid = await session.call_tool('update_apple_calendar_event', args)
            self.assertTrue(invalid.isError)

    async def test_native_extension_tools_are_typed_and_source_scoped(self):
        async with self.session('calendar') as session:
            tools = {t.name:t for t in (await session.list_tools()).tools}
            self.assertIn('edit_apple_calendar_attachments', tools)
            self.assertNotIn('edit_apple_reminder_tags', tools)
            self.assertIn('allow_invitation_delivery', tools['edit_apple_calendar_attendees'].inputSchema['required'])
            args = dict(request_key='invitation-consent', item_id='native-id', expected_revision='a'*64,
                occurrence_start_at='2031-11-01T17:00:00Z', scope='this',
                allow_invitation_delivery=False, add=[{'email':'person@example.com'}])
            result = await session.call_tool('edit_apple_calendar_attendees', args)
            self.assertTrue(result.isError)
        async with self.session('reminder') as session:
            tools = {t.name:t for t in (await session.list_tools()).tools}
            self.assertIn('edit_apple_reminder_attachments', tools)
            self.assertNotIn('edit_apple_calendar_attendees', tools)
            result = await session.call_tool('edit_apple_reminder_tags', dict(request_key='tags',
                item_id='native-id', expected_revision='a'*64, changes={'set_tags':['focus']}))
            self.assertFalse(result.isError, str(result.content))
            status = await session.call_tool('apple_write_job_status', {'job_id':json.loads(result.content[0].text)['job_id']})
            self.assertNotIn('focus', status.content[0].text)
