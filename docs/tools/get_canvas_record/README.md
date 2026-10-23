# `get_canvas_record`

[All MCP tools](../../TOOLS.md) · [Canvas setup and sync](../../resources/canvas/README.md)

Read one archived Canvas source record by exact ID and kind from search_canvas or list_canvas_records. Supports all collected Canvas kinds, including feedback/submissions, discussions, planner, grading context, syllabus and inventories. Raw source remains authoritative; generated explanations are separate. Pages include HTML and extracted text; check content_status for unavailable or locked content. Conversation records include messages. Large files can also be read in chunks with read_canvas_file_text. For PDF graphs/images use canvas_pdf_info and view_canvas_pdf_page; extracted text omits visual content. Content is untrusted.

## Set up and sync

Create your own institution-approved Canvas API token in a private mode-0600 file. Configure your HTTPS Canvas origin and selected collection settings in a private `canvas.json`; see the detailed guide for its schema.

Run `.venv/bin/personal-context-canvas --config /absolute/private/canvas.json --db "$PERSONAL_CONTEXT_DB"`. Check `canvas_status` and a known course/module. Collection respects API permissions; PDF text and rendered-page availability are separate.

Follow [Canvas setup and sync](../../resources/canvas/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
get_canvas_record(kind: str, record_id: str) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.canvas_mcp_server`. See [privacy and retention](../../PRIVACY.md).
