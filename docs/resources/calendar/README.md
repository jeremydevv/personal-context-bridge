# Apple Calendar

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../SETUP.md#apple-collection-on-a-mac)

## Set up this resource

Install the pinned Apple PIM tools on your Mac, grant Calendar access, and configure your selected calendars plus SSH archive destination in a private Apple configuration.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_calendar_status` for a later collection timestamp and query a known event.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.source_mcp_server --source calendar
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Optional native writes

Read [native write setup](../../SETUP.md#native-calendar-and-reminders-writes-through-a-mac) and [editing requirements](../../APPLE-PIM-EDITING.md). Set `PERSONAL_CONTEXT_APPLE_WRITE_ENABLED=1` only after the outbox, worker and authorized Mac receiver are configured. Require client approval for writes. `queued` is not native completion; inspect the completed receipt and native readback. Never automatically replay uncertain delivery.

## Tools

- [`apple_calendar_status`](../../tools/apple_calendar_status/README.md)
- [`apple_pim_capabilities`](../../tools/apple_pim_capabilities/README.md)
- [`apple_write_job_status`](../../tools/apple_write_job_status/README.md)
- [`cancel_apple_write_job`](../../tools/cancel_apple_write_job/README.md)
- [`delete_apple_calendar_event`](../../tools/delete_apple_calendar_event/README.md)
- [`edit_apple_calendar_attachments`](../../tools/edit_apple_calendar_attachments/README.md)
- [`edit_apple_calendar_attendees`](../../tools/edit_apple_calendar_attendees/README.md)
- [`force_refresh_apple_calendar`](../../tools/force_refresh_apple_calendar/README.md)
- [`get_apple_calendar_record`](../../tools/get_apple_calendar_record/README.md)
- [`inspect_native_apple_calendar_event`](../../tools/inspect_native_apple_calendar_event/README.md)
- [`list_apple_calendars`](../../tools/list_apple_calendars/README.md)
- [`pending_apple_write_jobs`](../../tools/pending_apple_write_jobs/README.md)
- [`queue_apple_calendar_event`](../../tools/queue_apple_calendar_event/README.md)
- [`search_apple_calendar`](../../tools/search_apple_calendar/README.md)
- [`set_apple_calendar_driving_time`](../../tools/set_apple_calendar_driving_time/README.md)
- [`set_apple_calendar_travel_time`](../../tools/set_apple_calendar_travel_time/README.md)
- [`upcoming_apple_calendar`](../../tools/upcoming_apple_calendar/README.md)
- [`update_apple_calendar_event`](../../tools/update_apple_calendar_event/README.md)
