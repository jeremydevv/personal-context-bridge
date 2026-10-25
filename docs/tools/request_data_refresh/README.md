# `request_data_refresh`

[All MCP tools](../../TOOLS.md) · [Personal context setup](../../resources/context/README.md)

Queue a durable refresh request and return `refresh_id`. Requires `PERSONAL_CONTEXT_REFRESH_ENABLED=1`; only then does this action appear. `mode` is `recent` or `full`. Omit sources on the main MCP for privately configured enabled sources; on a source MCP omission means its own source. A source connector rejects unrelated sources. Health/location are phone pushes, Google Timeline requires manual import, iCloud Drive needs its existing authentication, and summaries are derived work; a request does not manufacture fresh data or trigger unsupported collection.

## Call signature

```python
request_data_refresh(sources: list[str] = None, mode: str = "recent") -> dict
```

## Configuration and verification

Configure `PERSONAL_CONTEXT_REFRESH_CONFIG` to a private mode-0600 JSON file and `PERSONAL_CONTEXT_REFRESH_DIR` outside source checkouts. The encrypted ledger uses the private archive key; configuring the read tools does not install a worker or unlock provider access. Run the bounded refresh worker separately under the documented operator schedule. These tools never send mail, edit native records, mark messages read, or perform automatic login.

The existing `force_refresh_*` tools use the same ledger and return durable IDs. Source status tools retain old timestamp fields and add `data_refresh`. Clients with cached catalogs can read tracking via `get_personal_record(kind="data_refresh_status", record_id=refresh_id)` or `kind="data_source_status", record_id="all"`. Apple source record tools accept `record_id="data_refresh_status:REFRESH_ID"` or `data_source_status:SOURCE`; Canvas uses those kinds with its ordinary `record_id` argument.

## Implementation

Defined in `personal_context.refresh_mcp`, backed by `personal_context.refresh_tracking`. Health and Travel surfaces live in `iphone_context.read_mcp`; they share the same private ledger only when explicitly configured with the same archive key and refresh directory. See [privacy and retention](../../PRIVACY.md).
