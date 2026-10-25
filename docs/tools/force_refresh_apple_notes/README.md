# `force_refresh_apple_notes`

[All MCP tools](../../TOOLS.md) · [Apple Notes setup and sync](../../resources/note/README.md)

Queue a durable refresh request for this connector’s source (configured enabled sources on the main connector). Returns `refresh_id`; use `data_refresh_status` for correlated archive acknowledgement. Acceptance and later unrelated timestamps do not prove completion. Existing source scopes and native write permissions remain unchanged.

## Set up and sync

Grant Automation access to Notes on the Mac. Configure `all_notes` or supported selected folders and SSH delivery in your private Apple configuration. Locked or unavailable notes may lack readable bodies.

On the Mac: `.venv/bin/personal-context notes-sync --config /absolute/private/apple.json`. Check `apple_note_status` and read a known note; a title alone does not prove its body was collected.

Follow [Apple Notes setup and sync](../../resources/note/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
force_refresh_apple_notes() -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request returns a durable `refresh_id` and reports acceptance; use `data_refresh_status(refresh_id)` for correlated archive acknowledgement. A later unrelated timestamp is not completion evidence. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.source_mcp_server`. See [privacy and retention](../../PRIVACY.md).
