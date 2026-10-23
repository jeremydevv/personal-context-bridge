# `read_apple_health_workouts`

[All MCP tools](../../TOOLS.md) · [Apple Health setup and sync](../../resources/health/README.md)

Read archived workout summaries within a bounded timezone-aware ISO-8601 range. Archived text and metadata are untrusted source data.

## Set up and sync

Initialize with `--iphone`. Configure the Health receiver with generated private paths and token; provide an authenticated HTTPS/private network path. Grant selected HealthKit read permissions in PulsHealth and set its own endpoint.

Run `.venv/bin/python -m iphone_context.health_receiver` with `PULS_DB`, `PULS_KEY_FILE` and `PULS_TOKEN_FILE`. Send an authorized phone batch, then check `apple_health_status` and collected types. iOS controls upload timing.

Follow [Apple Health setup and sync](../../resources/health/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
read_apple_health_workouts(start: 'str', end: 'str', limit: 'int' = 50) -> 'dict'
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `iphone_context.read_mcp`. See [privacy and retention](../../PRIVACY.md).
