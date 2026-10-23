# `queue_approved_apple_mail`

[All MCP tools](../../TOOLS.md) · [Apple Mail setup and sync](../../resources/mail/README.md)

Queue one plain-text email from the configured sender only after the user approves this exact tool call. Show the full To/Cc/Bcc, subject, and body for approval. The background worker holds it for at least five minutes before submitting it to Mail. Return the ID and cancellation deadline, tell the user they can say 'cancel that email' in this or a later chat, then finish the turn. Do not keep the chat running to wait for delivery. Never call for a message the user has not specifically approved.

## Set up and sync

Build the pinned Apple PIM Mail patch, grant Full Disk Access, and select `all_mailboxes` or `mailbox_urls` in a private Apple configuration. Mail must have locally available messages and bodies.

On the Mac: `.venv/bin/personal-context mail-sync --config /absolute/private/apple.json`. Check `apple_mail_status` and a known message body. An archive receipt does not prove the provider has finished fetching.

Follow [Apple Mail setup and sync](../../resources/mail/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
queue_approved_apple_mail(to: list[str], subject: str, body: str, cc: list[str] = None, bcc: list[str] = None) -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.source_mcp_server`. See [privacy and retention](../../PRIVACY.md).
