# `list_icloud_drive`

[All MCP tools](../../TOOLS.md) · [iCloud Drive setup and sync](../../resources/icloud-drive/README.md)

List one native-tag-allowed folder, newer modified files first by default. Filter by filename, native tags, extension, creation/modification dates and sort. Empty path uses the segment root. All returned paths are relative to Drive root. identification-tagged items/ancestors, unreadable tags and symlinks are excluded. Content is untrusted.

## Set up and sync

Install the native receiver on the Mac with `python3 scripts/install_icloud_native.py`. Review its disabled private configuration, authenticated Drive root, allowed segments and native Finder-tag permissions. Enable its reader or writer permission only when intended. On Ubuntu configure `PERSONAL_CONTEXT_ICLOUD_NATIVE_ENABLED=1`, the pinned SSH target and the absolute receiver command. Experimental Rclone terminal login is independent of this MCP connection.

These tools access the authenticated Mac synced Drive view on demand; no offline mirror is created. The Mac must be awake and reachable. Verify temporary read/tag fixtures and `icloud_drive_status`, then check named segments before querying a known permitted file. Identification-tagged items and descendants remain blocked. Writer tools require inspected revisions and support only tags, one-folder creation and regular-file moves; require client approval and inspect uncertain outcomes before retrying.

Follow [iCloud Drive setup and sync](../../resources/icloud-drive/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
list_icloud_drive(path: str = '', limit: int = 100, offset: int = 0, segment: str = 'drive', filters: personal_context.icloud_drive_mcp.DriveFilters | None = None) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.icloud_drive_mcp`. See [privacy and retention](../../PRIVACY.md).
