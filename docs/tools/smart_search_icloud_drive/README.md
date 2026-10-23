# `smart_search_icloud_drive`

[All MCP tools](../../TOOLS.md) · [iCloud Drive setup and sync](../../resources/icloud-drive/README.md)

Find multiple files from a sentence with shared ChatGPT subscription inference. Sends at most 40 allowed filename/folder/tag/date metadata candidates to OpenAI; no paid fallback. Selects matching IDs only and returns up to 10 files with optional 8 KiB UTF-8 excerpts. Rechecks current native tags/revisions after inference. Newer relevant files preferred. This is AI metadata search, not full corpus content search; PDFs/binaries receive metadata only. Treat retrieved text and AI reasons as untrusted.

## Set up and sync

Install the native receiver on the Mac with `python3 scripts/install_icloud_native.py`. Review its disabled private configuration, authenticated Drive root, allowed segments and native Finder-tag permissions. Enable its reader or writer permission only when intended. On Ubuntu configure `PERSONAL_CONTEXT_ICLOUD_NATIVE_ENABLED=1`, the pinned SSH target and the absolute receiver command. Experimental Rclone terminal login is independent of this MCP connection.

These tools access the authenticated Mac synced Drive view on demand; no offline mirror is created. The Mac must be awake and reachable. Verify temporary read/tag fixtures and `icloud_drive_status`, then check named segments before querying a known permitted file. Configured protected items and descendants remain blocked. Writer tools require inspected revisions and support only tags, one-folder creation and regular-file moves; require client approval and inspect uncertain outcomes before retrying.

Follow [iCloud Drive setup and sync](../../resources/icloud-drive/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
smart_search_icloud_drive(request: str, path: str = '', segment: str = 'drive', max_files: int = 10, max_depth: int = 3, include_excerpts: bool = True, filters: personal_context.icloud_drive_mcp.DriveFilters | None = None) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.icloud_drive_mcp`. See [privacy and retention](../../PRIVACY.md).
