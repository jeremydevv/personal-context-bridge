# `get_canvas_explanation`

[All MCP tools](../../TOOLS.md) · [Canvas setup and sync](../../resources/canvas/README.md)

Read one exact generated Canvas summary and its source citation table, plus a bounded page of input evidence. Follow evidence.next_offset until eof. Facts/actions cite zero-based refs indices. Verify original Canvas IDs/digests before relying on generated claims; explanations are unverified snapshots, not live Canvas state.

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
get_canvas_explanation(summary_id: str, evidence_offset: int = 0, evidence_limit: int = 5) -> dict
```

## Verify a read

Check `canvas_summary_status` first. An unavailable result is expected in the public distribution. With a separately supplied compatible backend, query a known explanation and verify its source references. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.canvas_mcp_server`. See [privacy and retention](../../PRIVACY.md).
