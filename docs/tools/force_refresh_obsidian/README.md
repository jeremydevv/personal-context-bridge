# `force_refresh_obsidian`

[All MCP tools](../../TOOLS.md) · [Obsidian setup and sync](../../resources/obsidian/README.md)

Request the existing bidirectional iCloud reconciliation for the allowed Obsidian vaults. Acceptance is not completion; check obsidian_sync_status afterward. The sync job applies remote changes under its existing conflict and backup safeguards.

## Set up and sync

Set `OBSIDIAN_VAULT_ROOT` to your encrypted mount and `OBSIDIAN_VAULTS` to a comma-separated allowlist. Keep writes disabled unless intended. The bridge does not encrypt the vault directory itself.

Existing local vault files are read directly. For optional iCloud reconciliation, configure your own rclone remote and the documented environment, then use `scripts/obsidian_icloud_sync.sh --dry-run` before scheduled `--run`. Check `obsidian_sync_status` and a known note.

Follow [Obsidian setup and sync](../../resources/obsidian/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
force_refresh_obsidian() -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.obsidian_mcp_server`. See [privacy and retention](../../PRIVACY.md).
