# `inspect_native_apple_calendar_event`

[All MCP tools](../../TOOLS.md) · [Apple Calendar setup and sync](../../resources/calendar/README.md)

Read the LIVE native event and revision before editing/deleting. Use payload.id (not the archive's composite ID) and the original occurrence start with timezone. Exact occurrence matching; never choose an event by title. Requires reachable authorized Mac.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Calendar access, and configure your selected calendars plus SSH archive destination in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_calendar_status` for a later collection timestamp and query a known event.

Follow [Apple Calendar setup and sync](../../resources/calendar/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
inspect_native_apple_calendar_event(item_id: str, occurrence_start_at: str) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).
