# `get_visited_place`

[All MCP tools](../../TOOLS.md) · [Remembered places setup and sync](../../resources/places/README.md)

Read an exact place ID from search_visited_places with visits, context citations and optional private coordinates. Model summaries are unverified; venue and visit reason may be unknown.

## Set up and sync

Set up OwnTracks travel ingestion first. Set `IPHONE_TRAVEL_DB`, `IPHONE_ARCHIVE_KEY_FILE`, `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; enable `PERSONAL_CONTEXT_LOCATION_ENABLED=1`. Shared optional generated summaries use separate sign-in.

Run `.venv/bin/python -m personal_context.location_worker` on the archive host. Check `location_dictionary_status` for worker results and GPS fix freshness separately. Clustering and generated visit reasons remain uncertain.

Follow [Remembered places setup and sync](../../resources/places/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
get_visited_place(place_id: str, include_coordinates: bool = False) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.location_mcp`. See [privacy and retention](../../PRIVACY.md).
