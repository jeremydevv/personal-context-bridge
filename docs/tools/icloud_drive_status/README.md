# `icloud_drive_status`

[All MCP tools](../../TOOLS.md) · [iCloud Drive setup and sync](../../resources/icloud-drive/README.md)

Check iCloud Drive setup without exposing credentials. Set probe=true for a live read-only root listing. A configured session alone does not prove access or cross-server portability. Authentication happens only in the local terminal.

## Set up and sync

Follow the experimental pinned Rclone/libfido2 build and local authentication guide. Configure `PERSONAL_CONTEXT_ICLOUD_DIR` and the unlocked archive key. Security-key authentication requires your local interactive terminal.

There is no offline Drive sync: these tools make live read-only requests. Run `.venv/bin/python -m personal_context.icloud_setup prepare`, then `authenticate` and `verify` locally. Check `icloud_drive_status(probe=true)`; local configuration alone does not establish account access.

Follow [iCloud Drive setup and sync](../../resources/icloud-drive/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
icloud_drive_status(probe: bool = False) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.icloud_drive_mcp`. See [privacy and retention](../../PRIVACY.md).
