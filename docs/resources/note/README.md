# Apple Notes

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../SETUP.md#apple-collection-on-a-mac)

## Set up this resource

Grant Automation access to Notes on the Mac. Configure `all_notes` or supported selected folders and SSH delivery in your private Apple configuration. Locked or unavailable notes may lack readable bodies.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

On the Mac: `.venv/bin/personal-context notes-sync --config /absolute/private/apple.json`. Check `apple_note_status` and read a known note; a title alone does not prove its body was collected.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.source_mcp_server --source note
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Tools

- [`apple_note_status`](../../tools/apple_note_status/README.md)
- [`apple_note_timeline`](../../tools/apple_note_timeline/README.md)
- [`force_refresh_apple_notes`](../../tools/force_refresh_apple_notes/README.md)
- [`get_apple_note_record`](../../tools/get_apple_note_record/README.md)
- [`search_apple_note`](../../tools/search_apple_note/README.md)
