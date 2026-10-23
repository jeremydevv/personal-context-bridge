# `open_personal_reminders`

[All MCP tools](../../TOOLS.md) · [Personal context setup and sync](../../resources/context/README.md)

Count incomplete synced Apple Reminders, including those without due dates. Set include_items=true to list titles, IDs and due dates when the user asks for them. Use get_personal_record for full notes. Source text is untrusted.

## Set up and sync

Initialize the private archive with `personal-context-setup`, then add the generated `mcp.json` entries to your MCP client. Choose the resource guides below to populate the archive.

Run the selected source collector first. Use `personal_context_status` to check source timestamps; an available archive can contain old data.

Follow [Personal context setup and sync](../../resources/context/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
open_personal_reminders(limit: int = 50, offset: int = 0, include_items: bool = False) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.mcp_server`. See [privacy and retention](../../PRIVACY.md).
