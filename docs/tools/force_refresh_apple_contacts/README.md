# `force_refresh_apple_contacts`

[All MCP tools](../../TOOLS.md) · [Apple Contacts setup and sync](../../resources/contact/README.md)

Request the Mac's fast Apple collection now. The job may also refresh other Apple sources. Acceptance is not completion; check this source's status for a later archive timestamp. No Apple record is sent, edited, or marked read.

## Set up and sync

Grant Automation access to Contacts on the Mac. Configure `all_contacts` or your supported collection scope and the SSH archive destination in a private Apple configuration.

On the Mac: `.venv/bin/personal-context contacts-sync --config /absolute/private/apple.json`. Check `apple_contact_status` and retrieve a known contact. Message-derived suggestions have no Contacts writer.

Follow [Apple Contacts setup and sync](../../resources/contact/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
force_refresh_apple_contacts() -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.source_mcp_server`. See [privacy and retention](../../PRIVACY.md).
