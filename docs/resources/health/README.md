# Apple Health

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../SETUP.md#health-and-owntracks)

## Set up this resource

Initialize with `--iphone`. Configure the Health receiver with generated private paths and token; provide an authenticated HTTPS/private network path. Grant selected HealthKit read permissions in PulsHealth and set its own endpoint.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

Run `.venv/bin/python -m iphone_context.health_receiver` with `PULS_DB`, `PULS_KEY_FILE` and `PULS_TOKEN_FILE`. Send an authorized phone batch, then check `apple_health_status` and collected types. iOS controls upload timing.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m iphone_context.read_mcp --source health
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Tools

- [`apple_health_status`](../../tools/apple_health_status/README.md)
- [`list_apple_health_types`](../../tools/list_apple_health_types/README.md)
- [`read_apple_health_activity_days`](../../tools/read_apple_health_activity_days/README.md)
- [`read_apple_health_aggregates`](../../tools/read_apple_health_aggregates/README.md)
- [`read_apple_health_samples`](../../tools/read_apple_health_samples/README.md)
- [`read_apple_health_workout_route`](../../tools/read_apple_health_workout_route/README.md)
- [`read_apple_health_workout_series`](../../tools/read_apple_health_workout_series/README.md)
- [`read_apple_health_workouts`](../../tools/read_apple_health_workouts/README.md)
