# Apple Reminders

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../SETUP.md#apple-collection-on-a-mac)

## Set up this resource

Install the pinned Apple PIM tools on your Mac, grant Reminders access, and configure selected lists plus SSH archive delivery in a private Apple configuration.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_reminder_status` and a known reminder; collection does not complete or modify tasks.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.source_mcp_server --source reminder
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Optional native writes

Read [native write setup](../../SETUP.md#native-calendar-and-reminders-writes-through-a-mac) and [editing requirements](../../APPLE-PIM-EDITING.md). Set `PERSONAL_CONTEXT_APPLE_WRITE_ENABLED=1` only after the outbox, worker and authorized Mac receiver are configured. Require client approval for writes. `queued` is not native completion; inspect the completed receipt and native readback. Never automatically replay uncertain delivery.

## Tools

- [`add_apple_reminder_subtasks`](../../tools/add_apple_reminder_subtasks/README.md)
- [`apple_pim_capabilities`](../../tools/apple_pim_capabilities/README.md)
- [`apple_reminder_status`](../../tools/apple_reminder_status/README.md)
- [`apple_write_job_status`](../../tools/apple_write_job_status/README.md)
- [`cancel_apple_write_job`](../../tools/cancel_apple_write_job/README.md)
- [`delete_apple_reminder`](../../tools/delete_apple_reminder/README.md)
- [`edit_apple_reminder_attachments`](../../tools/edit_apple_reminder_attachments/README.md)
- [`edit_apple_reminder_tags`](../../tools/edit_apple_reminder_tags/README.md)
- [`force_refresh_apple_reminders`](../../tools/force_refresh_apple_reminders/README.md)
- [`get_apple_reminder_record`](../../tools/get_apple_reminder_record/README.md)
- [`inspect_native_apple_reminder`](../../tools/inspect_native_apple_reminder/README.md)
- [`list_apple_reminder_lists`](../../tools/list_apple_reminder_lists/README.md)
- [`open_apple_reminders`](../../tools/open_apple_reminders/README.md)
- [`pending_apple_write_jobs`](../../tools/pending_apple_write_jobs/README.md)
- [`queue_apple_reminder`](../../tools/queue_apple_reminder/README.md)
- [`search_apple_reminder`](../../tools/search_apple_reminder/README.md)
- [`set_apple_reminder_urgent`](../../tools/set_apple_reminder_urgent/README.md)
- [`upcoming_apple_reminder`](../../tools/upcoming_apple_reminder/README.md)
- [`update_apple_reminder`](../../tools/update_apple_reminder/README.md)
