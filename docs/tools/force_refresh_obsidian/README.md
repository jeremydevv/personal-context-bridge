# `force_refresh_obsidian`

[All MCP tools](../../TOOLS.md) · [Obsidian setup and sync](../../resources/obsidian/README.md)

Queue a durable refresh request for this connector’s source (configured enabled sources on the main connector). Returns `refresh_id`; use `data_refresh_status` for correlated archive acknowledgement. Acceptance and later unrelated timestamps do not prove completion. Existing source scopes and native write permissions remain unchanged.

## Set up and sync

Set `OBSIDIAN_VAULT_ROOT` to your encrypted mount and `OBSIDIAN_VAULTS` to a comma-separated allowlist. Keep writes disabled unless intended. The bridge does not encrypt the vault directory itself.

Existing local vault files are read directly. For optional iCloud reconciliation, configure your own rclone remote and the documented environment, then use `scripts/obsidian_icloud_sync.sh --dry-run` before scheduled `--run`. Check `obsidian_sync_status` and a known note.

Follow [Obsidian setup and sync](../../resources/obsidian/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
force_refresh_obsidian() -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request returns a durable `refresh_id` and reports acceptance; use `data_refresh_status(refresh_id)` for correlated archive acknowledgement. A later unrelated timestamp is not completion evidence. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.obsidian_mcp_server`. See [privacy and retention](../../PRIVACY.md).
