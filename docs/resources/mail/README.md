# Apple Mail

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../SETUP.md#apple-collection-on-a-mac)

## Set up this resource

Build the pinned Apple PIM Mail patch, grant Full Disk Access, and select `all_mailboxes` or `mailbox_urls` in a private Apple configuration. Mail must have locally available messages and bodies.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

On the Mac: `.venv/bin/personal-context mail-sync --config /absolute/private/apple.json`. Check `apple_mail_status` and a known message body. An archive receipt does not prove the provider has finished fetching.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.source_mcp_server --source mail
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Optional sending

Mail sending needs separate sender/account configuration and a worker; see [optional actions](../../SETUP.md#scheduling-backups-and-optional-actions). It is disabled by default. Require exact-message approval; the worker holds queued messages for five minutes. Collection does not enable sending.

## Tools

- [`apple_mail_send_status`](../../tools/apple_mail_send_status/README.md)
- [`apple_mail_status`](../../tools/apple_mail_status/README.md)
- [`apple_mail_timeline`](../../tools/apple_mail_timeline/README.md)
- [`cancel_pending_apple_mail`](../../tools/cancel_pending_apple_mail/README.md)
- [`force_refresh_apple_mail`](../../tools/force_refresh_apple_mail/README.md)
- [`get_apple_mail_record`](../../tools/get_apple_mail_record/README.md)
- [`pending_apple_mail`](../../tools/pending_apple_mail/README.md)
- [`queue_approved_apple_mail`](../../tools/queue_approved_apple_mail/README.md)
- [`search_apple_mail`](../../tools/search_apple_mail/README.md)
