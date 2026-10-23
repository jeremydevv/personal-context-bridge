# `read_iphone_travel_locations`

[All MCP tools](../../TOOLS.md) · [Travel and Timeline setup and sync](../../resources/travel/README.md)

Read up to 200 archived location points within timezone-aware ISO-8601 start and end times, at most 366 days apart. Returns exact coordinates and receipt time.

## Set up and sync

Initialize with `--iphone`. Configure the OwnTracks receiver, private credentials, HTTPS/private route and phone location permissions. Historical Timeline is a separate manual JSON import, documented in the setup guide.

Run `.venv/bin/python -m iphone_context.location_receiver` with `OWNTRACKS_DB`, `OWNTRACKS_KEY_FILE` and `OWNTRACKS_CREDENTIAL_FILE`. Configure OwnTracks HTTP mode with the `/pub` endpoint. Check `iphone_travel_status`; historical imports do not establish fresh GPS.

Follow [Travel and Timeline setup and sync](../../resources/travel/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
read_iphone_travel_locations(start: 'str', end: 'str', limit: 'int' = 200) -> 'dict'
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `iphone_context.read_mcp`. See [privacy and retention](../../PRIVACY.md).
