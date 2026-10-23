# `pending_apple_write_jobs`

[All MCP tools](../../TOOLS.md) · [Calendar setup and sync](../../resources/calendar/README.md) · [Reminders setup and sync](../../resources/reminder/README.md)

List queued, delivering, and needs_review jobs with IDs and safe state metadata. No titles or notes returned. A queued job waits for an authorized, reachable Mac.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Reminders access, and configure selected lists plus SSH archive delivery in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_reminder_status` and a known reminder; collection does not complete or modify tasks.

Follow [Calendar setup and sync](../../resources/calendar/README.md) · [Reminders setup and sync](../../resources/reminder/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
pending_apple_write_jobs() -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).
