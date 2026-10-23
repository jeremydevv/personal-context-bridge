# `apple_message_attachment_info`

[All MCP tools](../../TOOLS.md) · [Apple Messages setup and sync](../../resources/message/README.md)

Check whether a Messages attachment GUID has archived file bytes, its type, size, and archive time. Use a GUID from get_apple_message_record. A missing file may have metadata in Messages but no local original.

## Set up and sync

Grant Full Disk Access to the Mac collection process. Configure `all_messages` or a supported bounded scope plus SSH delivery. Attachment metadata and original file bytes are separate.

On the Mac: `.venv/bin/personal-context messages-sync --config /absolute/private/apple.json`. For opt-in originals, run `attachment-sync --config /absolute/private/apple.json --limit 50` with the same executable. Check `apple_message_status` and attachment availability.

Follow [Apple Messages setup and sync](../../resources/message/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
apple_message_attachment_info(attachment_guid: str) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.source_mcp_server`. See [privacy and retention](../../PRIVACY.md).
