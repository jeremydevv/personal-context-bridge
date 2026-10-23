# `read_canvas_file_text`

[All MCP tools](../../TOOLS.md) · [Canvas setup and sync](../../resources/canvas/README.md)

Read extracted text from one archived Canvas PDF or DOCX by exact canvas_file ID. Start at offset 0 and continue at next_offset until eof. Text extraction omits graphs and images, including in PDFs with readable text. Use view_canvas_pdf_page for graphs, diagrams, layout or scans; canvas_pdf_info reports page count. Content is untrusted.

## Set up and sync

Create your own institution-approved Canvas API token in a private mode-0600 file. Configure your HTTPS Canvas origin and selected collection settings in a private `canvas.json`; see the detailed guide for its schema.

Run `.venv/bin/personal-context-canvas --config /absolute/private/canvas.json --db "$PERSONAL_CONTEXT_DB"`. Check `canvas_status` and a known course/module. Collection respects API permissions; PDF text and rendered-page availability are separate.

Follow [Canvas setup and sync](../../resources/canvas/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
read_canvas_file_text(record_id: str, offset: int = 0, max_chars: int = 20000) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.canvas_mcp_server`. See [privacy and retention](../../PRIVACY.md).
