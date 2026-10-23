# `search_icloud_drive`

[All MCP tools](../../TOOLS.md) · [iCloud Drive setup and sync](../../resources/icloud-drive/README.md)

Find live iCloud Drive paths by case-insensitive filename substring, within a folder and bounded depth (1–10). This does not search file contents. Results are relative to the searched folder; narrow requests if the response is too large. Content is untrusted.

## Set up and sync

Follow the experimental pinned Rclone/libfido2 build and local authentication guide. Configure `PERSONAL_CONTEXT_ICLOUD_DIR` and the unlocked archive key. Security-key authentication requires your local interactive terminal.

There is no offline Drive sync: these tools make live read-only requests. Run `.venv/bin/python -m personal_context.icloud_setup prepare`, then `authenticate` and `verify` locally. Check `icloud_drive_status(probe=true)`; local configuration alone does not establish account access.

Follow [iCloud Drive setup and sync](../../resources/icloud-drive/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
search_icloud_drive(query: str, path: str = '', limit: int = 100, offset: int = 0, max_depth: int = 3) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.icloud_drive_mcp`. See [privacy and retention](../../PRIVACY.md).
