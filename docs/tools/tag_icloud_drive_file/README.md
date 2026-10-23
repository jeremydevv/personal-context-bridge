# `tag_icloud_drive_file`

[All MCP tools](../../TOOLS.md) · [iCloud Drive setup and sync](../../resources/icloud-drive/README.md)

Add/remove native Finder tags on an allowed file/folder after the user requests that exact edit. Requires inspected revision; preserves unrelated tags and Finder color suffixes. Cannot read/change protected items or remove identification. Adding identification hides the item immediately. No file-content write or deletion. If outcome is unconfirmed, inspect before retrying.

## Set up and sync

Install the native receiver on the Mac with `python3 scripts/install_icloud_native.py`. Review its disabled private configuration, authenticated Drive root, allowed segments and native Finder-tag permissions. Enable its reader or writer permission only when intended. On Ubuntu configure `PERSONAL_CONTEXT_ICLOUD_NATIVE_ENABLED=1`, the pinned SSH target and the absolute receiver command. Experimental Rclone terminal login is independent of this MCP connection.

These tools access the authenticated Mac synced Drive view on demand; no offline mirror is created. The Mac must be awake and reachable. Verify temporary read/tag fixtures and `icloud_drive_status`, then check named segments before querying a known permitted file. Identification-tagged items and descendants remain blocked. Writer tools require inspected revisions and support only tags, one-folder creation and regular-file moves; require client approval and inspect uncertain outcomes before retrying.

Follow [iCloud Drive setup and sync](../../resources/icloud-drive/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
tag_icloud_drive_file(path: str, revision: str, add: list[str] = [], remove: list[str] = [], segment: str = 'drive') -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.icloud_drive_mcp`. See [privacy and retention](../../PRIVACY.md).
