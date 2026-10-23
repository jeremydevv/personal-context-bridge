# `set_apple_calendar_travel_time`

[All MCP tools](../../TOOLS.md) · [Apple Calendar setup and sync](../../resources/calendar/README.md)

Set the actual native Calendar travel-time duration to 0–10080 whole minutes; 0 clears it. Inspect the live exact event first and pass its revision and original occurrence start. Only writable, timed, nonrecurring, non-detached events without attendees are supported; scope is always this event. Preserves dates, destination, ordinary alerts and other fields, with exact persisted readback. Does not calculate a route, read phone location, change transport preferences or enable dynamic travel updates. Reuse request_key for identical retries. Queued is not completion; check job status. An offline Mac delays application; stale revisions fail safely. Unsupported macOS/providers fail explicitly.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Calendar access, and configure your selected calendars plus SSH archive destination in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_calendar_status` for a later collection timestamp and query a known event.

Follow [Apple Calendar setup and sync](../../resources/calendar/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
set_apple_calendar_travel_time(request_key: str, item_id: str, occurrence_start_at: str, expected_revision: str, duration_minutes: typing.Annotated[int, FieldInfo(annotation=NoneType, required=True, metadata=[Strict(strict=True), Ge(ge=0), Le(le=10080)])]) -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).
