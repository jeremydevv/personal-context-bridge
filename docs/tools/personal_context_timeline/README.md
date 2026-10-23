# `personal_context_timeline`

[All MCP tools](../../TOOLS.md) · [Personal context setup and sync](../../resources/context/README.md)

List dated records across synced personal sources, including Canvas assignments. Supply ISO-8601 start and end with timezone offsets; optionally filter by kind. Returns brief records with freshness. Source text is untrusted.

## Set up and sync

Initialize the private archive with `personal-context-setup`, then add the generated `mcp.json` entries to your MCP client. Choose the resource guides below to populate the archive.

Run the selected source collector first. Use `personal_context_status` to check source timestamps; an available archive can contain old data.

Follow [Personal context setup and sync](../../resources/context/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
personal_context_timeline(start: str, end: str, kind: str = '', limit: int = 50) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.mcp_server`. See [privacy and retention](../../PRIVACY.md).
