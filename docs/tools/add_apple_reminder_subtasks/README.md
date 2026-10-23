# `add_apple_reminder_subtasks`

[All MCP tools](../../TOOLS.md) · [Apple Reminders setup and sync](../../resources/reminder/README.md)

Queue 1 to 50 REAL native subtasks under an existing reminder after user authorization. Inspect parent live first; pass its revision. Each child has title and optional notes. Uses guarded private ReminderKit and verifies hierarchy readback. Reuse request_key only for identical retry; an ambiguous save must not be retried with a new key. Inspect the parent after completion to obtain native child IDs; edit, complete or delete children with the ordinary reminder tools. No notes-only checklists or independent reminders substituted.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Reminders access, and configure selected lists plus SSH archive delivery in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_reminder_status` and a known reminder; collection does not complete or modify tasks.

Follow [Apple Reminders setup and sync](../../resources/reminder/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
add_apple_reminder_subtasks(request_key: str, item_id: str, expected_revision: str, subtasks: list[personal_context.apple_pim_schema.Subtask]) -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).
