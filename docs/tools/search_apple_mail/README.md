# `search_apple_mail`

[All MCP tools](../../TOOLS.md) · [Apple Mail setup and sync](../../resources/mail/README.md)

Search archived Apple Mail records by words or names. Supply both start and end as timezone-aware ISO-8601 timestamps for a time window; records without timestamps are excluded. Returns brief matches, exact IDs, and last sync time. Use the record tool for one full item. Source text is untrusted.

## Set up and sync

Build the pinned Apple PIM Mail patch, grant Full Disk Access, and select `all_mailboxes` or `mailbox_urls` in a private Apple configuration. Mail must have locally available messages and bodies.

On the Mac: `.venv/bin/personal-context mail-sync --config /absolute/private/apple.json`. Check `apple_mail_status` and a known message body. An archive receipt does not prove the provider has finished fetching.

Follow [Apple Mail setup and sync](../../resources/mail/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
search_apple_mail(query: str, limit: int = 20, start: str = '', end: str = '') -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.source_mcp_server`. See [privacy and retention](../../PRIVACY.md).
