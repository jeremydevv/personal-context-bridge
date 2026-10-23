# `force_refresh_canvas`

[All MCP tools](../../TOOLS.md) · [Canvas setup and sync](../../resources/canvas/README.md)

Request a new student Canvas collection on the Mac. Acceptance does not mean collection finished; check canvas_status for a later timestamp. This does not submit or edit Canvas work.

## Set up and sync

Create your own institution-approved Canvas API token in a private mode-0600 file. Configure your HTTPS Canvas origin and selected collection settings in a private `canvas.json`; see the detailed guide for its schema.

Run `.venv/bin/personal-context-canvas --config /absolute/private/canvas.json --db "$PERSONAL_CONTEXT_DB"`. Check `canvas_status` and a known course/module. Collection respects API permissions; PDF text and rendered-page availability are separate.

Follow [Canvas setup and sync](../../resources/canvas/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
force_refresh_canvas() -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.canvas_mcp_server`. See [privacy and retention](../../PRIVACY.md).
