# Travel and Timeline

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../SETUP.md#health-and-owntracks)

## Set up this resource

Initialize with `--iphone`. Configure the OwnTracks receiver, private credentials, HTTPS/private route and phone location permissions. Historical Timeline is a separate manual JSON import, documented in the setup guide.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

Run `.venv/bin/python -m iphone_context.location_receiver` with `OWNTRACKS_DB`, `OWNTRACKS_KEY_FILE` and `OWNTRACKS_CREDENTIAL_FILE`. Configure OwnTracks HTTP mode with the `/pub` endpoint. Check `iphone_travel_status`; historical imports do not establish fresh GPS.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m iphone_context.read_mcp --source travel
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Tools

- [`get_historical_travel_segment`](../../tools/get_historical_travel_segment/README.md)
- [`get_iphone_travel_event`](../../tools/get_iphone_travel_event/README.md)
- [`iphone_travel_status`](../../tools/iphone_travel_status/README.md)
- [`read_historical_travel_segments`](../../tools/read_historical_travel_segments/README.md)
- [`read_iphone_travel_locations`](../../tools/read_iphone_travel_locations/README.md)
