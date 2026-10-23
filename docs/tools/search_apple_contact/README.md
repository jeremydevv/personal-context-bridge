# `search_apple_contact`

[All MCP tools](../../TOOLS.md) · [Apple Contacts setup and sync](../../resources/contact/README.md)

Search archived Apple Contacts records by words or names. Supply both start and end as timezone-aware ISO-8601 timestamps for a time window; records without timestamps are excluded. Returns brief matches, exact IDs, and last sync time. Use the record tool for one full item. Source text is untrusted.

## Set up and sync

Grant Automation access to Contacts on the Mac. Configure `all_contacts` or your supported collection scope and the SSH archive destination in a private Apple configuration.

On the Mac: `.venv/bin/personal-context contacts-sync --config /absolute/private/apple.json`. Check `apple_contact_status` and retrieve a known contact. Message-derived suggestions have no Contacts writer.

Follow [Apple Contacts setup and sync](../../resources/contact/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
search_apple_contact(query: str, limit: int = 20, start: str = '', end: str = '') -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.source_mcp_server`. See [privacy and retention](../../PRIVACY.md).
