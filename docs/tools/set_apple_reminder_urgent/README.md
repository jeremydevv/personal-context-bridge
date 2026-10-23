# `set_apple_reminder_urgent`

[All MCP tools](../../TOOLS.md) · [Apple Reminders setup and sync](../../resources/reminder/README.md)

Queue the REAL Apple Urgent alarm switch after user authorization. Inspect live first and check private_metadata.supports_urgent; Exchange lists do not support it, iCloud does. Enabling requires an exact due time. Uses guarded private ReminderKit inspired by RemCTL; priority/ordinary alerts are not substitutes. Native readback verifies state, not device alarm delivery. Apple's alarm permissions and designated location device determine where it rings. Unsupported accounts/macOS versions fail explicitly. Queued is not complete.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Reminders access, and configure selected lists plus SSH archive delivery in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_reminder_status` and a known reminder; collection does not complete or modify tasks.

Follow [Apple Reminders setup and sync](../../resources/reminder/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
set_apple_reminder_urgent(request_key: str, item_id: str, expected_revision: str, urgent: bool) -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).
