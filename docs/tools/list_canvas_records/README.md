# `list_canvas_records`

[All MCP tools](../../TOOLS.md) · [Canvas setup and sync](../../resources/canvas/README.md)

Browse any archived Canvas kind with pagination. Use submission for own feedback/history/rubrics, discussion/discussion_entry for prompts/replies, syllabus/page, assignment_group/grading_period/grading_standard, planner_item/planner_note/planner_override/todo/missing_submission, file_inventory/folder, section/user/tab, group/calendar_event or quiz/quiz_submission. Optional exact course_record_id filters course resources; account lists account resources. collection_status reports available/partial/unavailable plus checked times and explicit planner/calendar windows. An empty result without successful coverage is not proof of no data. Source text is untrusted.

## Set up and sync

Create your own institution-approved Canvas API token in a private mode-0600 file. Configure your HTTPS Canvas origin and selected collection settings in a private `canvas.json`; see the detailed guide for its schema.

Run `.venv/bin/personal-context-canvas --config /absolute/private/canvas.json --db "$PERSONAL_CONTEXT_DB"`. Check `canvas_status` and a known course/module. Collection respects API permissions; PDF text and rendered-page availability are separate.

Follow [Canvas setup and sync](../../resources/canvas/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
list_canvas_records(kind: str, account: str = '', course_record_id: str = '', limit: int = 50, offset: int = 0) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.canvas_mcp_server`. See [privacy and retention](../../PRIVACY.md).
