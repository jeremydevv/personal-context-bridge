# `update_apple_calendar_event`

[All MCP tools](../../TOOLS.md) · [Apple Calendar setup and sync](../../resources/calendar/README.md)

Queue a precise native event patch after user authorization. Inspect live first; pass its revision. Absent fields are preserved; empty notes/location/url clears, alerts=[] clears alerts, recurrence=null removes repeat. For End Repeat, use only recurrence_end={date:'YYYY-MM-DD', timezone:'IANA name'} with scope='future'; the date is inclusive and existing rule selectors are preserved. This is an end-only patch, not recurrence replacement. Dates are offset ISO instants; timezone is an IANA name. Calendar accepts an exact existing destination ID (preferred) or unique name. Scope 'this'/'future' must be explicit; never infer a series-wide change. Alerts are minutes before start. Physical location/start changes automatically recalculate car travel from fresh phone location unless automatic_driving=false is explicitly requested. All-day boundaries must be local midnights with exclusive end. Queued is not completion; revision conflict means inspect again. Existing participants may be notified by ordinary edits; require explicit notification consent before allow_invitation_delivery=true. Use dedicated attendee/attachment tools for those native fields.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Calendar access, and configure your selected calendars plus SSH archive destination in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_calendar_status` for a later collection timestamp and query a known event.

Follow [Apple Calendar setup and sync](../../resources/calendar/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
update_apple_calendar_event(request_key: str, item_id: str, occurrence_start_at: str, expected_revision: str, scope: str, changes: personal_context.apple_pim_schema.CalendarChanges, automatic_driving: bool = True, allow_invitation_delivery: bool = False) -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).
