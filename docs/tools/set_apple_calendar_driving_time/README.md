# `set_apple_calendar_driving_time`

[All MCP tools](../../TOOLS.md) · [Apple Calendar setup and sync](../../resources/calendar/README.md)

Calculate CAR travel from a fresh phone location to this event's place through Apple Maps, then queue its real Calendar travel duration and mapped destination. Inspect event first and pass its revision. Requires configured encrypted travel archive, phone fix within five minutes and accuracy within 250m, and reachable Mac. Ambiguous destinations fail; no home/server-location guesses. Estimates expire after five minutes before application. This is an estimate at save time, not continuous tracking or proof of a time-to-leave notification. Ordinary event creates/location/start edits calculate it automatically unless automatic_driving=false is explicitly requested.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Calendar access, and configure your selected calendars plus SSH archive destination in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_calendar_status` for a later collection timestamp and query a known event.

Follow [Apple Calendar setup and sync](../../resources/calendar/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
set_apple_calendar_driving_time(request_key: str, item_id: str, occurrence_start_at: str, expected_revision: str) -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).
