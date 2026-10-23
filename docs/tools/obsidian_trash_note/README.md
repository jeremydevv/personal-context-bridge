# `obsidian_trash_note`

[All MCP tools](../../TOOLS.md) · [Obsidian setup and sync](../../resources/obsidian/README.md)

Remove a Markdown note at a known SHA-256 revision, keeping a private encrypted backup. Use only on explicit user request. Requires server-side write enablement.

## Set up and sync

Set `OBSIDIAN_VAULT_ROOT` to your encrypted mount and `OBSIDIAN_VAULTS` to a comma-separated allowlist. Keep writes disabled unless intended. The bridge does not encrypt the vault directory itself.

Existing local vault files are read directly. For optional iCloud reconciliation, configure your own rclone remote and the documented environment, then use `scripts/obsidian_icloud_sync.sh --dry-run` before scheduled `--run`. Check `obsidian_sync_status` and a known note.

Follow [Obsidian setup and sync](../../resources/obsidian/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
obsidian_trash_note(path: str, expected_sha256: str, vault: str = '') -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.obsidian_mcp_server`. See [privacy and retention](../../PRIVACY.md).
