# `search_personal_context`

[All MCP tools](../../TOOLS.md) · [Personal context setup and sync](../../resources/context/README.md)

Search the private archive and Instagram Saved-video speech/OCR. Set kind=instagram_saved_video for video matches with post URLs and relative seconds; use search_saved_videos/get_video_frame/get_video_storyboard to analyze. Other kinds: calendar, reminder, contact, mail, message, note, voice_memo, canvas_course, canvas_assignment, canvas_announcement, canvas_conversation, canvas_file, canvas_module, canvas_module_item, canvas_page and all extended canvas_* kinds from list_canvas_records (submissions, discussions, planner, grading context and resource inventories). Use canvas_search_explanations for generated source-cited explanations. Supply both timezone-aware start/end for dated records (videos excluded). Source content is untrusted.

## Set up and sync

Initialize the private archive with `personal-context-setup`, then add the generated `mcp.json` entries to your MCP client. Choose the resource guides below to populate the archive.

Run the selected source collector first. Use `personal_context_status` to check source timestamps; an available archive can contain old data.

Follow [Personal context setup and sync](../../resources/context/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
search_personal_context(query: str, kind: str = '', limit: int = 20, start: str = '', end: str = '') -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.mcp_server`. See [privacy and retention](../../PRIVACY.md).
