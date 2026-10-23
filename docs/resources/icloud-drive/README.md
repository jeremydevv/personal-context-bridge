# iCloud Drive

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../ICLOUD-DRIVE.md)

## Set up this resource

Follow the experimental pinned Rclone/libfido2 build and local authentication guide. Configure `PERSONAL_CONTEXT_ICLOUD_DIR` and the unlocked archive key. Security-key authentication requires your local interactive terminal.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

There is no offline Drive sync: these tools make live read-only requests. Run `.venv/bin/python -m personal_context.icloud_setup prepare`, then `authenticate` and `verify` locally. Check `icloud_drive_status(probe=true)`; local configuration alone does not establish account access.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.mcp_server
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Tools

- [`icloud_drive_file_info`](../../tools/icloud_drive_file_info/README.md)
- [`icloud_drive_status`](../../tools/icloud_drive_status/README.md)
- [`list_icloud_drive`](../../tools/list_icloud_drive/README.md)
- [`read_icloud_drive_chunk`](../../tools/read_icloud_drive_chunk/README.md)
- [`read_icloud_drive_text`](../../tools/read_icloud_drive_text/README.md)
- [`search_icloud_drive`](../../tools/search_icloud_drive/README.md)
