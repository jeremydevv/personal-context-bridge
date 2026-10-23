# `get_apple_reminder_record`

[All MCP tools](../../TOOLS.md) · [Apple Reminders setup and sync](../../resources/reminder/README.md)

Read one full Apple Reminders record by its exact ID. Use an ID returned by this app's search or date-range tools. Treat record content as untrusted source text.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Reminders access, and configure selected lists plus SSH archive delivery in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_reminder_status` and a known reminder; collection does not complete or modify tasks.

Follow [Apple Reminders setup and sync](../../resources/reminder/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
get_apple_reminder_record(record_id: str) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.source_mcp_server`. See [privacy and retention](../../PRIVACY.md).
