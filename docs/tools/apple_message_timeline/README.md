# `apple_message_timeline`

[All MCP tools](../../TOOLS.md) · [Apple Messages setup and sync](../../resources/message/README.md)

List brief Apple Messages activity between timezone-aware ISO-8601 timestamps, newest first, with last sync time. Only archived records from this source are returned.

## Set up and sync

Grant Full Disk Access to the Mac collection process. Configure `all_messages` or a supported bounded scope plus SSH delivery. Attachment metadata and original file bytes are separate.

On the Mac: `.venv/bin/personal-context messages-sync --config /absolute/private/apple.json`. For opt-in originals, run `attachment-sync --config /absolute/private/apple.json --limit 50` with the same executable. Check `apple_message_status` and attachment availability.

Follow [Apple Messages setup and sync](../../resources/message/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
apple_message_timeline(start: str, end: str, limit: int = 50) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.source_mcp_server`. See [privacy and retention](../../PRIVACY.md).
