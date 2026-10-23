# `read_place_visits`

[All MCP tools](../../TOOLS.md) · [Remembered places setup and sync](../../resources/places/README.md)

Read observed stay bounds and source GPS IDs for a place or date window. Supply both timezone-aware start/end, at most 366 days. Gaps do not prove continuous presence; source matches do not establish attendance or visit purpose.

## Set up and sync

Set up OwnTracks travel ingestion first. Set `IPHONE_TRAVEL_DB`, `IPHONE_ARCHIVE_KEY_FILE`, `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; enable `PERSONAL_CONTEXT_LOCATION_ENABLED=1`. Shared optional generated summaries use separate sign-in.

Run `.venv/bin/python -m personal_context.location_worker` on the archive host. Check `location_dictionary_status` for worker results and GPS fix freshness separately. Clustering and generated visit reasons remain uncertain.

Follow [Remembered places setup and sync](../../resources/places/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
read_place_visits(place_id: str = '', start: str = '', end: str = '', limit: int = 50) -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.location_mcp`. See [privacy and retention](../../PRIVACY.md).
