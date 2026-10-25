# `data_refresh_status`

[All MCP tools](../../TOOLS.md) · [Personal context setup](../../resources/context/README.md)

Read durable request state without starting collection. A queued request or supervisor acceptance is not completion. Inspect each child source: only acknowledged batches correlated to this request establish archive ingestion. Missing provider access, offline devices, incomplete coverage, and derived processing remain explicit. Unknown IDs and unavailable tracking do not imply completion.

## Call signature

```python
data_refresh_status(refresh_id: str) -> dict
```

## Configuration and verification

Configure `PERSONAL_CONTEXT_REFRESH_CONFIG` to a private mode-0600 JSON file and `PERSONAL_CONTEXT_REFRESH_DIR` outside source checkouts. The encrypted ledger uses the private archive key; configuring the read tools does not install a worker or unlock provider access. Run the bounded refresh worker separately under the documented operator schedule. These tools never send mail, edit native records, mark messages read, or perform automatic login.

The existing `force_refresh_*` tools use the same ledger and return durable IDs. Source status tools retain old timestamp fields and add `data_refresh`. Clients with cached catalogs can read tracking via `get_personal_record(kind="data_refresh_status", record_id=refresh_id)` or `kind="data_source_status", record_id="all"`. Apple source record tools accept `record_id="data_refresh_status:REFRESH_ID"` or `data_source_status:SOURCE`; Canvas uses those kinds with its ordinary `record_id` argument.

## Local pipeline receipts

Obsidian reconciliation and Saved-video processing emit a receipt only when their invocation receives `PERSONAL_CONTEXT_REFRESH_ID`, `PERSONAL_CONTEXT_REFRESH_ATTEMPT` and the matching `PERSONAL_CONTEXT_REFRESH_SOURCE`. A successful receipt is emitted while that invocation still holds its source lock. Obsidian dry runs, failures and lock skips cannot complete a request. Saved-video cooldowns and incomplete processing report partial coverage; a stale processor report cannot prove this invocation succeeded. These are local pipeline results, separate from core archive SQL acknowledgements and upstream device/provider freshness. Scheduled invocations without tracking identity stay quiet.

## Implementation

Defined in `personal_context.refresh_mcp`, backed by `personal_context.refresh_tracking`. Health and Travel surfaces live in `iphone_context.read_mcp`; they share the same private ledger only when explicitly configured with the same archive key and refresh directory. See [privacy and retention](../../PRIVACY.md).
