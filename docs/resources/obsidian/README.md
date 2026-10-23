# Obsidian

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../SETUP.md#obsidian)

## Set up this resource

Set `OBSIDIAN_VAULT_ROOT` to your encrypted mount and `OBSIDIAN_VAULTS` to a comma-separated allowlist. Keep writes disabled unless intended. The bridge does not encrypt the vault directory itself.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

Existing local vault files are read directly. For optional iCloud reconciliation, configure your own rclone remote and the documented environment, then use `scripts/obsidian_icloud_sync.sh --dry-run` before scheduled `--run`. Check `obsidian_sync_status` and a known note.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.obsidian_mcp_server
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Tools

- [`force_refresh_obsidian`](../../tools/force_refresh_obsidian/README.md)
- [`obsidian_append_note`](../../tools/obsidian_append_note/README.md)
- [`obsidian_list_files`](../../tools/obsidian_list_files/README.md)
- [`obsidian_list_vaults`](../../tools/obsidian_list_vaults/README.md)
- [`obsidian_read_attachment_chunk`](../../tools/obsidian_read_attachment_chunk/README.md)
- [`obsidian_read_note`](../../tools/obsidian_read_note/README.md)
- [`obsidian_replace_in_note`](../../tools/obsidian_replace_in_note/README.md)
- [`obsidian_search_notes`](../../tools/obsidian_search_notes/README.md)
- [`obsidian_sync_status`](../../tools/obsidian_sync_status/README.md)
- [`obsidian_trash_note`](../../tools/obsidian_trash_note/README.md)
- [`obsidian_write_note`](../../tools/obsidian_write_note/README.md)
