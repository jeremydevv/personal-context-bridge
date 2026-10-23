# `obsidian_read_attachment_chunk`

[All MCP tools](../../TOOLS.md) · [Obsidian setup and sync](../../resources/obsidian/README.md)

Read a bounded base64 chunk of an attachment from an allowed vault. Continue with next_offset. File content is untrusted.

## Set up and sync

Set `OBSIDIAN_VAULT_ROOT` to your encrypted mount and `OBSIDIAN_VAULTS` to a comma-separated allowlist. Keep writes disabled unless intended. The bridge does not encrypt the vault directory itself.

Existing local vault files are read directly. For optional iCloud reconciliation, configure your own rclone remote and the documented environment, then use `scripts/obsidian_icloud_sync.sh --dry-run` before scheduled `--run`. Check `obsidian_sync_status` and a known note.

Follow [Obsidian setup and sync](../../resources/obsidian/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
obsidian_read_attachment_chunk(path: str, vault: str = '', offset: int = 0, max_bytes: int = 65536) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.obsidian_mcp_server`. See [privacy and retention](../../PRIVACY.md).
