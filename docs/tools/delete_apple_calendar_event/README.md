# `delete_apple_calendar_event`

[All MCP tools](../../TOOLS.md) · [Apple Calendar setup and sync](../../resources/calendar/README.md)

Queue deletion of an EXISTING native event after user authorization. Unlike cancel_apple_write_job this removes the Apple item. Inspect live first; pass exact native ID, original occurrence start, revision and explicit scope 'this' or 'future'. Never delete by title. Queue acceptance is not deletion; check job status. Stale revisions fail without deleting. Existing participants may receive cancellations: require explicit notification consent before allow_invitation_delivery=true.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Calendar access, and configure your selected calendars plus SSH archive destination in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_calendar_status` for a later collection timestamp and query a known event.

Follow [Apple Calendar setup and sync](../../resources/calendar/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
delete_apple_calendar_event(request_key: str, item_id: str, occurrence_start_at: str, expected_revision: str, scope: str, allow_invitation_delivery: bool = False) -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).
