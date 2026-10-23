# `edit_apple_calendar_attendees`

[All MCP tools](../../TOOLS.md) · [Apple Calendar setup and sync](../../resources/calendar/README.md)

Queue real native attendee additions/removals after user approval of exact email addresses AND invitation/cancellation delivery. This can send real provider notifications; never call merely to draft an invitation. Requires live inspection, organizer rights and private_metadata.supports_attendee_edits. Explicit scope this/future, native exact event ID and revision required. Does not impersonate another organizer or remove self/organizer. Existing invitees and unrelated fields are preserved. Native readback confirms roster, not recipient delivery. Unsupported providers/macOS fail explicitly; needs_review must not be replayed.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Calendar access, and configure your selected calendars plus SSH archive destination in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_calendar_status` for a later collection timestamp and query a known event.

Follow [Apple Calendar setup and sync](../../resources/calendar/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
edit_apple_calendar_attendees(request_key: str, item_id: str, occurrence_start_at: str, expected_revision: str, scope: str, allow_invitation_delivery: bool, add: list[personal_context.apple_pim_schema.Attendee] | None = None, remove: list[str] | None = None) -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).
