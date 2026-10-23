# `apple_note_timeline`

[All MCP tools](../../TOOLS.md) · [Apple Notes setup and sync](../../resources/note/README.md)

List brief Apple Notes activity between timezone-aware ISO-8601 timestamps, newest first, with last sync time. Only archived records from this source are returned.

## Set up and sync

Grant Automation access to Notes on the Mac. Configure `all_notes` or supported selected folders and SSH delivery in your private Apple configuration. Locked or unavailable notes may lack readable bodies.

On the Mac: `.venv/bin/personal-context notes-sync --config /absolute/private/apple.json`. Check `apple_note_status` and read a known note; a title alone does not prove its body was collected.

Follow [Apple Notes setup and sync](../../resources/note/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
apple_note_timeline(start: str, end: str, limit: int = 50) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.source_mcp_server`. See [privacy and retention](../../PRIVACY.md).
