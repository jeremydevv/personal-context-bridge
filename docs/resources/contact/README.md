# Apple Contacts

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../SETUP.md#apple-collection-on-a-mac)

## Set up this resource

Grant Automation access to Contacts on the Mac. Configure `all_contacts` or your supported collection scope and the SSH archive destination in a private Apple configuration.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

On the Mac: `.venv/bin/personal-context contacts-sync --config /absolute/private/apple.json`. Check `apple_contact_status` and retrieve a known contact. Message-derived suggestions have no Contacts writer.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.source_mcp_server --source contact
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Tools

- [`apple_contact_activity`](../../tools/apple_contact_activity/README.md)
- [`apple_contact_status`](../../tools/apple_contact_status/README.md)
- [`apple_contact_timeline`](../../tools/apple_contact_timeline/README.md)
- [`force_refresh_apple_contacts`](../../tools/force_refresh_apple_contacts/README.md)
- [`get_apple_contact_record`](../../tools/get_apple_contact_record/README.md)
- [`search_apple_contact`](../../tools/search_apple_contact/README.md)
