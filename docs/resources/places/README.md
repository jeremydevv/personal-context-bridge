# Remembered places

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../LOCATION-CONTEXT.md)

## Set up this resource

Set up OwnTracks travel ingestion first. Set `IPHONE_TRAVEL_DB`, `IPHONE_ARCHIVE_KEY_FILE`, `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; enable `PERSONAL_CONTEXT_LOCATION_ENABLED=1`. Shared optional generated summaries use separate sign-in.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

Run `.venv/bin/python -m personal_context.location_worker` on the archive host. Check `location_dictionary_status` for worker results and GPS fix freshness separately. Clustering and generated visit reasons remain uncertain.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.mcp_server
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Tools

- [`get_visited_place`](../../tools/get_visited_place/README.md)
- [`location_dictionary_status`](../../tools/location_dictionary_status/README.md)
- [`read_place_visits`](../../tools/read_place_visits/README.md)
- [`search_visited_places`](../../tools/search_visited_places/README.md)
