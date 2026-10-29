# `apple_pim_capabilities`

[All MCP tools](../../TOOLS.md) · [Calendar setup and sync](../../resources/calendar/README.md) · [Reminders setup and sync](../../resources/reminder/README.md)

Report this adapter's field support. Unsupported features must not be silently replaced with notes, priority, or unrelated reminders. Mac reachability and connector discovery are separate from support.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Reminders access, and configure selected lists plus SSH archive delivery in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_reminder_status` and a known reminder; collection does not complete or modify tasks.

Follow [Calendar setup and sync](../../resources/calendar/README.md) · [Reminders setup and sync](../../resources/reminder/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
apple_pim_capabilities() -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).

## Reminder organization limits

The adapter cannot discover/assign list sections, reparent an existing reminder,
or promote a child to the top level. These operations are reported in
`unsupported`; no organization write tools or queue operations are registered.
Unsupported parent/section fields are rejected before queueing.

`add_apple_reminder_subtasks(request_key, item_id, expected_revision, subtasks)`
creates NEW children; it does not move existing reminders. Both that operation
and the `parent_id`/`subtasks` metadata returned by
`inspect_native_apple_reminder(item_id)` rely on **private ReminderKit**. They do
not satisfy a requirement to use only supported public Apple APIs.

Apple's documented [EKReminder interface](https://developer.apple.com/documentation/eventkit/ekreminder)
has no parent/child or section properties. The inspected Mac Reminders scripting
dictionary exposes a read-only reminder container, no child enumeration element,
and no section class. No supported mutation route has been established. Do not
substitute list moves, recreated reminders, notes, or direct Apple database edits.
A future implementation requires a supported Mac adapter and isolated native tests
proving ID/field preservation, revision checks, cycle rejection, uncertain-delivery
handling, and readback before these operations can be advertised as available.
