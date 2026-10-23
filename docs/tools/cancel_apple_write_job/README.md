# `cancel_apple_write_job`

[All MCP tools](../../TOOLS.md) · [Calendar setup and sync](../../resources/calendar/README.md) · [Reminders setup and sync](../../resources/reminder/README.md)

Cancel a queued native write by its job ID, including from a later chat. Once delivery begins cancellation cannot stop or undo native creation. Inspect the returned state.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Reminders access, and configure selected lists plus SSH archive delivery in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_reminder_status` and a known reminder; collection does not complete or modify tasks.

Follow [Calendar setup and sync](../../resources/calendar/README.md) · [Reminders setup and sync](../../resources/reminder/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
cancel_apple_write_job(job_id: str) -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).
