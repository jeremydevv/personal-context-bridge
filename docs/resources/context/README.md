# Personal context

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../SETUP.md#archive-server-and-mcp-client)

## Set up this resource

Initialize the private archive with `personal-context-setup`, then add the generated `mcp.json` entries to your MCP client. Choose the resource guides below to populate the archive.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

Run the selected source collector first. Use `personal_context_status` to check source timestamps; an available archive can contain old data.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.mcp_server
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Refresh tracking

The [common refresh tools](../../tools/request_data_refresh/README.md) return durable request IDs. Read `data_refresh_status` for correlated archive acknowledgement; a later unrelated timestamp is not proof that a request completed. Source status tools preserve timestamps and add tracking. Read status is available without enabling refresh actions.

## Tools

- [`apple_contact_activity`](../../tools/apple_contact_activity/README.md)
- [`apple_message_attachment_info`](../../tools/apple_message_attachment_info/README.md)
- [`force_refresh_personal_context`](../../tools/force_refresh_personal_context/README.md)
- [`get_personal_record`](../../tools/get_personal_record/README.md)
- [`open_personal_reminders`](../../tools/open_personal_reminders/README.md)
- [`personal_context_daily_summary`](../../tools/personal_context_daily_summary/README.md)
- [`personal_context_health`](../../tools/personal_context_health/README.md)
- [`personal_context_status`](../../tools/personal_context_status/README.md)
- [`personal_context_timeline`](../../tools/personal_context_timeline/README.md)
- [`read_apple_message_attachment_chunk`](../../tools/read_apple_message_attachment_chunk/README.md)
- [`read_apple_message_attachment_text`](../../tools/read_apple_message_attachment_text/README.md)
- [`search_personal_context`](../../tools/search_personal_context/README.md)
- [`upcoming_personal_events`](../../tools/upcoming_personal_events/README.md)
- [`view_apple_message_image`](../../tools/view_apple_message_image/README.md)
