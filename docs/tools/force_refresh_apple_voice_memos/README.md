# `force_refresh_apple_voice_memos`

[All MCP tools](../../TOOLS.md) · [Apple Voice Memos setup and sync](../../resources/voice_memo/README.md)

Queue a durable refresh request for this connector’s source (configured enabled sources on the main connector). Returns `refresh_id`; use `data_refresh_status` for correlated archive acknowledgement. Acceptance and later unrelated timestamps do not prove completion. Existing source scopes and native write permissions remain unchanged.

## Set up and sync

Enable `all_voice_memos` in the private Mac configuration and configure the existing SSH transport. Install `.[voice]` for optional local transcription and embeddings. Missing iCloud audio must first hydrate on the Mac.

On the Mac: `.venv/bin/personal-context voice-memos-sync --config /absolute/private/apple.json`. On the archive host run `.venv/bin/python -m personal_context.voice_memos_worker process --db "$PERSONAL_CONTEXT_DB"`. Check `apple_voice_memo_status`, transcript coverage and original-audio availability separately.

Follow [Apple Voice Memos setup and sync](../../resources/voice_memo/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
force_refresh_apple_voice_memos() -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request returns a durable `refresh_id` and reports acceptance; use `data_refresh_status(refresh_id)` for correlated archive acknowledgement. A later unrelated timestamp is not completion evidence. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.voice_memos_mcp`. See [privacy and retention](../../PRIVACY.md).
