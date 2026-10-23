# `update_apple_reminder`

[All MCP tools](../../TOOLS.md) · [Apple Reminders setup and sync](../../resources/reminder/README.md)

Queue a precise reminder patch after user authorization. Inspect live first and pass its revision. Absent fields are preserved; notes/url='' clears; due_at='' removes due time; alerts=[] clears ordinary timed alerts; recurrence/location_alarm=null clears that property. completed=true/false completes/reopens. priority is 0 none, 1 high, 5 medium, 9 low, NOT a native Urgent alarm. list_name accepts an existing exact ID (preferred) or unique name. Alert offsets before due can shift the displayed reminder time; explain this before approval. Changing a repeating reminder's completion may advance its recurrence. Queued is not completed; stale revisions fail safely.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Reminders access, and configure selected lists plus SSH archive delivery in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_reminder_status` and a known reminder; collection does not complete or modify tasks.

Follow [Apple Reminders setup and sync](../../resources/reminder/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
update_apple_reminder(request_key: str, item_id: str, expected_revision: str, changes: personal_context.apple_pim_schema.ReminderChanges) -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).
