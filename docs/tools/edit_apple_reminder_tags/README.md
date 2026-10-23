# `edit_apple_reminder_tags`

[All MCP tools](../../TOOLS.md) · [Apple Reminders setup and sync](../../resources/reminder/README.md)

Queue REAL synced Reminders tags after approval. Inspect live first; check supports_tags. set_tags replaces all tags ([] clears); alternatively add_tags/remove_tags preserve untouched tags. Names are 1-80 letters/numbers/underscore/hyphen without # or spaces. Guarded ReminderKit save and native readback, not hashtags appended to title/notes. Requires supporting account/macOS, exact native ID and live revision.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Reminders access, and configure selected lists plus SSH archive delivery in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_reminder_status` and a known reminder; collection does not complete or modify tasks.

Follow [Apple Reminders setup and sync](../../resources/reminder/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
edit_apple_reminder_tags(request_key: str, item_id: str, expected_revision: str, changes: personal_context.apple_pim_schema.TagChanges) -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).
