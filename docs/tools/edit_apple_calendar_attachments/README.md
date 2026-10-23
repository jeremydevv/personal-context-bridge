# `edit_apple_calendar_attachments`

[All MCP tools](../../TOOLS.md) · [Apple Calendar setup and sync](../../resources/calendar/README.md)

Queue native Calendar attachment additions/removals after user approval. Inspect live first; use exact attachment IDs from private_metadata for removals. Supports PNG/JPEG/PDF only when the existing calendar supports native attachments. Each add requires safe filename, media_type, exact base64 bytes and SHA256 (2 MiB/file, 4 MiB/batch, max 5). No paths/URLs fetched, no public uploads, no PDF-to-image substitution. Bytes stay in encrypted queue and private temporary receiver files; completion clears queued bytes. Events with invitees require explicit allow_invitation_delivery=true approval because provider updates may notify them. Exact event/occurrence/revision and this/future scope required. Native file readback verifies persistence, not cross-device sync.

## Set up and sync

Install the pinned Apple PIM tools on your Mac, grant Calendar access, and configure your selected calendars plus SSH archive destination in a private Apple configuration.

On the Mac: `.venv/bin/personal-context sync --config /absolute/private/apple.json`. Check `apple_calendar_status` for a later collection timestamp and query a known event.

Follow [Apple Calendar setup and sync](../../resources/calendar/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
edit_apple_calendar_attachments(request_key: str, item_id: str, occurrence_start_at: str, expected_revision: str, scope: str, add: list[personal_context.apple_pim_schema.Attachment] | None = None, remove: list[str] | None = None, allow_invitation_delivery: bool = False) -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.apple_write_mcp`. See [privacy and retention](../../PRIVACY.md).
