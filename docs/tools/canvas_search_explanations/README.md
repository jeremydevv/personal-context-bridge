# `canvas_search_explanations`

[All MCP tools](../../TOOLS.md) · [Canvas setup and sync](../../resources/canvas/README.md)

Search AI-generated Canvas explanations with source references, separately from source text. kind filters a Canvas source kind (e.g. submission, page, discussion, assignment). For all Canvas sources omit kind. Results can be incomplete/stale; check canvas_summary_status and follow source IDs with get_canvas_record. Generated claims are unverified and never replace original content.

## Availability and source setup

The public distribution does **not** ship the optional `summary_mcp` backend.
Without it this compatibility tool returns `available: false` and
`state: unsupported_capability`, not generated content or an empty successful
search. Status reports processing as `unavailable`; changing Wi-Fi or collection
settings cannot install the missing backend. No public backend installation
procedure is provided.

For original evidence, use `search_canvas`, `list_canvas_records` and
`get_canvas_record`. Follow [Canvas setup and sync](../../resources/canvas/README.md)
for either institution-approved token collection or the Firefox-session option.
Source collection and optional generated explanations are separate capabilities.

## Call signature

```python
canvas_search_explanations(query: str = '', kind: str = '', limit: int = 10, offset: int = 0) -> dict
```

## Verify a read

Check `canvas_summary_status` first. An unavailable result is expected in the public distribution. With a separately supplied compatible backend, query a known explanation and verify its source references. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.canvas_mcp_server`. See [privacy and retention](../../PRIVACY.md).
