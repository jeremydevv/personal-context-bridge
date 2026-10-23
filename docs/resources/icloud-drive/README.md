# iCloud Drive

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../ICLOUD-DRIVE.md#native-finder-tags-folder-scopes-and-writer-permissions)

## Set up this resource

Install the native receiver on the Mac with `python3 scripts/install_icloud_native.py`. Review its disabled private configuration, authenticated Drive root, allowed segments and native Finder-tag permissions. Enable its reader or writer permission only when intended. On Ubuntu configure `PERSONAL_CONTEXT_ICLOUD_NATIVE_ENABLED=1`, the pinned SSH target and the absolute receiver command. Experimental Rclone terminal login is independent of this MCP connection.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

These tools access the authenticated Mac synced Drive view on demand; no offline mirror is created. The Mac must be awake and reachable. Verify temporary read/tag fixtures and `icloud_drive_status`, then check named segments before querying a known permitted file. Identification-tagged items and descendants remain blocked. Writer tools require inspected revisions and support only tags, one-folder creation and regular-file moves; require client approval and inspect uncertain outcomes before retrying.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.mcp_server
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Tools

- [`create_icloud_drive_folder`](../../tools/create_icloud_drive_folder/README.md)
- [`icloud_drive_file_info`](../../tools/icloud_drive_file_info/README.md)
- [`icloud_drive_status`](../../tools/icloud_drive_status/README.md)
- [`list_icloud_drive`](../../tools/list_icloud_drive/README.md)
- [`list_icloud_drive_segments`](../../tools/list_icloud_drive_segments/README.md)
- [`move_icloud_drive_file`](../../tools/move_icloud_drive_file/README.md)
- [`read_icloud_drive_chunk`](../../tools/read_icloud_drive_chunk/README.md)
- [`read_icloud_drive_text`](../../tools/read_icloud_drive_text/README.md)
- [`search_icloud_drive`](../../tools/search_icloud_drive/README.md)
- [`smart_search_icloud_drive`](../../tools/smart_search_icloud_drive/README.md)
- [`tag_icloud_drive_file`](../../tools/tag_icloud_drive_file/README.md)
