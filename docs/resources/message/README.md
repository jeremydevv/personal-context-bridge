# Apple Messages

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../SETUP.md#apple-collection-on-a-mac)

## Set up this resource

Grant Full Disk Access to the Mac collection process. Configure `all_messages` or a supported bounded scope plus SSH delivery. Attachment metadata and original file bytes are separate.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

On the Mac: `.venv/bin/personal-context messages-sync --config /absolute/private/apple.json`. For opt-in originals, run `attachment-sync --config /absolute/private/apple.json --limit 50` with the same executable. Check `apple_message_status` and attachment availability.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.source_mcp_server --source message
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Tools

- [`apple_message_attachment_info`](../../tools/apple_message_attachment_info/README.md)
- [`apple_message_status`](../../tools/apple_message_status/README.md)
- [`apple_message_timeline`](../../tools/apple_message_timeline/README.md)
- [`force_refresh_apple_messages`](../../tools/force_refresh_apple_messages/README.md)
- [`get_apple_message_record`](../../tools/get_apple_message_record/README.md)
- [`read_apple_message_attachment_chunk`](../../tools/read_apple_message_attachment_chunk/README.md)
- [`read_apple_message_attachment_text`](../../tools/read_apple_message_attachment_text/README.md)
- [`search_apple_message`](../../tools/search_apple_message/README.md)
- [`view_apple_message_image`](../../tools/view_apple_message_image/README.md)
