import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from personal_context.store import Store
from personal_context.episodes import EpisodeBuilder

try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from sqlcipher3 import dbapi2 as sqlcipher
except ImportError:
    ClientSession = None


@unittest.skipIf(ClientSession is None, "MCP SDK is not installed")
class McpIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_lists_read_only_tools_and_answers_from_stored_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "context.sqlite3"
            key_file = Path(directory) / "key"
            key_file.write_bytes(os.urandom(32))
            key_file.chmod(0o600)
            store = Store(database, key_file=key_file)
            store.ingest({
                "schema": 1, "source": "apple-pim", "kind": "calendar",
                "scope": "calendar:personal", "collected_at": "2026-09-30T20:00:00Z",
                "complete": True, "records": [{"id": "event-1", "title": "Sample appointment",
                    "body": "Bring documents", "start": "2026-10-02T14:00:00Z",
                    "payload": {"calendar": "Personal"}}],
            })
            store.ingest({"schema": 1, "source": "apple-local", "kind": "message",
                          "scope": "messages:test", "collected_at": "2026-10-01T00:00:00Z",
                          "complete": True,
                          "records": [{"id": "message-1", "title": "Sample discussion",
                                       "body": "Prototype milestones",
                                       "start": "2026-09-30T16:00:00Z"}]})
            store.ingest({"schema": 1, "source": "apple-pim", "kind": "reminder",
                          "scope": "reminder:personal", "collected_at": "2026-10-01T00:00:00Z",
                          "complete": True,
                          "records": [{"id": "todo-1", "title": "Sample unfinished task",
                                       "body": "private details " * 30,
                                       "payload": {"isCompleted": False}}]})
            store.ingest({"schema": 1, "source": "canvas-lms", "kind": "canvas_file",
                          "scope": "school:course:42", "collected_at": "2026-10-06T00:00:00Z",
                          "complete": True,
                          "records": [{"id": "canvas:school:file:42:88", "title": "reading.docx",
                                       "body": "First paragraph. Second paragraph.",
                                       "payload": {"mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                                   "extraction_status": "available"}}]})
            EpisodeBuilder(store, lambda items: {"summary": "Prototype milestones were discussed.",
                                                "citations": ["message:message-1"]},
                           model="synthetic").sync_day("2026-09-30")
            store.ingest({"schema": 1, "source": "apple-local", "kind": "voice_memo",
                          "scope": "voice-memos:all", "collected_at": "2026-10-20T00:00:00Z",
                          "complete": False, "records": [{"id": "voice-demo", "title": "Demo memo",
                          "body": "Fictional full voice transcript.", "payload": {}}]})
            store.close()
            server = StdioServerParameters(
                command=sys.executable,
                args=["-m", "personal_context.mcp_server"],
                env={**os.environ, "PYTHONPATH":str(Path(__file__).resolve().parents[1]/"src"),
                     "PERSONAL_CONTEXT_REFRESH_ENABLED":"0", "PERSONAL_CONTEXT_DB": str(database),
                     "PERSONAL_CONTEXT_KEY_FILE": str(key_file),
                     "PERSONAL_CONTEXT_REFRESH_DIR":str(Path(directory)/"refresh-state")},
            )
            async with stdio_client(server) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    self.assertEqual({"data_refresh_status", "data_source_status",
                                      "search_personal_context", "get_personal_record",
                                      "upcoming_personal_events", "personal_context_timeline",
                                      "open_personal_reminders",
                                      "personal_context_status",
                                      "personal_context_health", "personal_context_daily_summary",
                                      "apple_contact_activity", "apple_message_attachment_info",
                                      "read_apple_message_attachment_text", "read_apple_message_attachment_chunk",
                                      "view_apple_message_image", "canvas_status", "search_canvas", "canvas_inbox",
                                      "get_canvas_record", "upcoming_canvas_assignments", "canvas_modules", "canvas_module_items", "list_canvas_records", "canvas_summary_status", "canvas_search_explanations", "get_canvas_explanation",
                                      "read_canvas_file_text", "canvas_pdf_info", "view_canvas_pdf_page", "search_apple_voice_memo", "get_apple_voice_memo_record",
                                      "read_apple_voice_memo_transcript", "apple_voice_memo_timeline",
                                      "apple_voice_memo_status", "icloud_drive_status", "list_icloud_drive",
                                      "search_icloud_drive", "icloud_drive_file_info",
                                      "read_icloud_drive_text", "read_icloud_drive_chunk",
                                      "list_icloud_drive_segments", "smart_search_icloud_drive",
                                      "tag_icloud_drive_file", "create_icloud_drive_folder", "move_icloud_drive_file"}, names)
                    voice = await session.call_tool("get_personal_record", {
                        "kind": "voice_memo", "record_id": "voice-demo"})
                    self.assertFalse(voice.isError)
                    self.assertIn("Fictional full voice transcript", str(voice.structuredContent or voice.content))
                    canvas = await session.call_tool("read_canvas_file_text", {
                        "record_id": "canvas:school:file:42:88", "offset": 17,
                        "max_chars": 17})
                    self.assertFalse(canvas.isError)
                    self.assertIn("Second paragraph", str(canvas.structuredContent or canvas.content))
                    result = await session.call_tool("search_personal_context", {"query": "appointment"})
                    self.assertFalse(result.isError)
                    self.assertIn("Sample appointment", str(result.structuredContent or result.content))
                    self.assertIn("2026-09-30T20:00:00Z", str(result.structuredContent or result.content))
                    dated = await session.call_tool("search_personal_context", {
                        "query": "appointment", "kind": "calendar",
                        "start": "2026-10-02T14:00:00Z", "end": "2026-10-02T15:00:00Z"})
                    self.assertFalse(dated.isError)
                    self.assertIn("Sample appointment", str(dated.structuredContent or dated.content))
                    timeline = await session.call_tool("personal_context_timeline", {
                        "start": "2026-10-02T00:00:00Z", "end": "2026-10-03T00:00:00Z"})
                    self.assertFalse(timeline.isError)
                    self.assertIn("Sample appointment", str(timeline.structuredContent or timeline.content))
                    episode = await session.call_tool("personal_context_daily_summary", {"day": "2026-09-30"})
                    self.assertFalse(episode.isError)
                    self.assertIn("message:message-1", str(episode.structuredContent or episode.content))
                    open_tasks = await session.call_tool("open_personal_reminders", {})
                    self.assertFalse(open_tasks.isError)
                    count_only = json.loads(open_tasks.content[0].text)
                    self.assertEqual(1, count_only["total"])
                    self.assertEqual([], count_only["results"])
                    listed_tasks = await session.call_tool("open_personal_reminders", {"include_items": True})
                    self.assertFalse(listed_tasks.isError)
                    listed = json.loads(listed_tasks.content[0].text)
                    self.assertEqual("Sample unfinished task", listed["results"][0]["title"])


if __name__ == "__main__":
    unittest.main()
