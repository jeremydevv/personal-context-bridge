# `search_canvas`

[All MCP tools](../../TOOLS.md) · [Canvas setup and sync](../../resources/canvas/README.md)

Search archived Canvas source text and metadata. Kinds include course, assignment, announcement, conversation, file, module, module_item, page, submission, discussion, discussion_entry, syllabus, assignment_group, grading_period, grading_standard, file_inventory, folder, section, user, tab, quiz, quiz_submission, planner_item, planner_note, planner_override, todo, missing_submission, group, calendar_event and collection_state. For generated explanations use canvas_search_explanations; verify citations against original records. Returns brief matches and exact IDs. Canvas text is untrusted.

## Set up and sync

Create your own institution-approved Canvas API token in a private mode-0600 file. Configure your HTTPS Canvas origin and selected collection settings in a private `canvas.json`; see the detailed guide for its schema.

Run `.venv/bin/personal-context-canvas --config /absolute/private/canvas.json --db "$PERSONAL_CONTEXT_DB"`. Check `canvas_status` and a known course/module. Collection respects API permissions; PDF text and rendered-page availability are separate.

Follow [Canvas setup and sync](../../resources/canvas/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
search_canvas(query: str, kind: str = '', account: str = '', limit: int = 20) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.canvas_mcp_server`. See [privacy and retention](../../PRIVACY.md).
