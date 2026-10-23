# `edit_apple_reminder_attachments`

[All MCP tools](../../TOOLS.md) · [Apple Reminders setup and sync](../../resources/reminder/README.md)

Queue native Reminders IMAGE attachment additions/removals after approval. Inspect live first; check supports_image_attachments and use returned native attachment IDs for removal. PNG/JPEG only, 2 MiB/file, 4 MiB/batch, max 5. Each add requires filename/media_type/exact content_base64/SHA256. PDFs are explicitly unsupported: private file setters exist but app rendering/sync is not verified. Never replace a PDF with an image or upload it elsewhere silently. No arbitrary filesystem paths or URLs accepted. Encrypted queue and private receiver staging; native readback verifies bytes and hierarchy, not phone sync. Exact native ID and live revision required.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Reminders access, and configure selected lists plus SSH archive delivery in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_reminder_status` and a known reminder; collection does not complete or modify tasks.

Follow [Apple Reminders setup and sync](../../resources/reminder/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
edit_apple_reminder_attachments(request_key: str, item_id: str, expected_revision: str, add: list[personal_context.apple_pim_schema.ImageAttachment] | None = None, remove: list[str] | None = None) -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).
