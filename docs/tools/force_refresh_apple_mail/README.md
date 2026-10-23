# `force_refresh_apple_mail`

[All MCP tools](../../TOOLS.md) · [Apple Mail setup and sync](../../resources/mail/README.md)

Request the Mac's fast Apple collection now. The job may also refresh other Apple sources. Acceptance is not completion; check this source's status for a later archive timestamp. No Apple record is sent, edited, or marked read.

## Set up and sync

Build the pinned Apple PIM Mail patch, grant Full Disk Access, and select `all_mailboxes` or `mailbox_urls` in a private Apple configuration. Mail must have locally available messages and bodies.

On the Mac: `.venv/bin/personal-context mail-sync --config /absolute/private/apple.json`. Check `apple_mail_status` and a known message body. An archive receipt does not prove the provider has finished fetching.

Follow [Apple Mail setup and sync](../../resources/mail/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
force_refresh_apple_mail() -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.source_mcp_server`. See [privacy and retention](../../PRIVACY.md).
