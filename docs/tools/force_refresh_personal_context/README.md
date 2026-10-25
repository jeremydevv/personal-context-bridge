# `force_refresh_personal_context`

[All MCP tools](../../TOOLS.md) · [Personal context setup and sync](../../resources/context/README.md)

Queue a durable refresh request for this connector’s source (configured enabled sources on the main connector). Returns `refresh_id`; use `data_refresh_status` for correlated archive acknowledgement. Acceptance and later unrelated timestamps do not prove completion. Existing source scopes and native write permissions remain unchanged.

## Set up and sync

Initialize the private archive with `personal-context-setup`, then add the generated `mcp.json` entries to your MCP client. Choose the resource guides below to populate the archive.

Run the selected source collector first. Use `personal_context_status` to check source timestamps; an available archive can contain old data.

Follow [Personal context setup and sync](../../resources/context/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
force_refresh_personal_context() -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request returns a durable `refresh_id` and reports acceptance; use `data_refresh_status(refresh_id)` for correlated archive acknowledgement. A later unrelated timestamp is not completion evidence. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.mcp_server`. See [privacy and retention](../../PRIVACY.md).
