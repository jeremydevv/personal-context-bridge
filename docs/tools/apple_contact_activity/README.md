# `apple_contact_activity`

[All MCP tools](../../TOOLS.md) · [Apple Contacts setup and sync](../../resources/contact/README.md)

Find bounded Mail and Messages activity for one exact Apple Contact ID. Only recorded email and phone values match; duplicate identifiers are excluded. Group chats are labeled. Returns source IDs and freshness without full bodies. Use source record tools for details. Timestamps require timezone offsets.

## Set up and sync

Grant Automation access to Contacts on the Mac. Configure `all_contacts` or your supported collection scope and the SSH archive destination in a private Apple configuration.

On the Mac: `.venv/bin/personal-context contacts-sync --config /absolute/private/apple.json`. Check `apple_contact_status` and retrieve a known contact. Message-derived suggestions have no Contacts writer.

Follow [Apple Contacts setup and sync](../../resources/contact/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
apple_contact_activity(contact_id: str, start: str, end: str, limit: int = 50) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.source_mcp_server`. See [privacy and retention](../../PRIVACY.md).
