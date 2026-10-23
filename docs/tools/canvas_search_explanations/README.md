# `canvas_search_explanations`

[All MCP tools](../../TOOLS.md) · [Canvas setup and sync](../../resources/canvas/README.md)

Search AI-generated Canvas explanations with source references, separately from source text. kind filters a Canvas source kind (e.g. submission, page, discussion, assignment). For all Canvas sources omit kind. Results can be incomplete/stale; check canvas_summary_status and follow source IDs with get_canvas_record. Generated claims are unverified and never replace original content.

## Set up and sync

Create your own institution-approved Canvas API token in a private mode-0600 file. Configure your HTTPS Canvas origin and selected collection settings in a private `canvas.json`; see the detailed guide for its schema.

Run `.venv/bin/personal-context-canvas --config /absolute/private/canvas.json --db "$PERSONAL_CONTEXT_DB"`. Check `canvas_status` and a known course/module. Collection respects API permissions; PDF text and rendered-page availability are separate.

Follow [Canvas setup and sync](../../resources/canvas/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
canvas_search_explanations(query: str = '', kind: str = '', limit: int = 10, offset: int = 0) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.canvas_mcp_server`. See [privacy and retention](../../PRIVACY.md).
