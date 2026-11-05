# `canvas_summary_status`

[All MCP tools](../../TOOLS.md) · [Canvas setup and sync](../../resources/canvas/README.md)

Check optional generated Canvas explanation availability separately from source syncing. Only with a separately supplied compatible backend can existing summary processing run while collection is paused; new Canvas feature processing then requires explicit Wi-Fi resume configuration. Pending/unavailable is not summarized. Generated text is unverified; read exact source citations.

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
canvas_summary_status() -> dict
```

## Verify a read

Check `canvas_summary_status` first. An unavailable result is expected in the public distribution. With a separately supplied compatible backend, query a known explanation and verify its source references. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.canvas_mcp_server`. See [privacy and retention](../../PRIVACY.md).
