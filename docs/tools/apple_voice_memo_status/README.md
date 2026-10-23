# `apple_voice_memo_status`

[All MCP tools](../../TOOLS.md) · [Apple Voice Memos setup and sync](../../resources/voice_memo/README.md)

Check Mac collection time and counts for recordings, indexed transcripts, generated summaries and embeddings. Empty Mac caches do not establish iCloud/iPhone coverage. Existing records remain readable while Mac is off.

## Set up and sync

Enable `all_voice_memos` in the private Mac configuration and configure the existing SSH transport. Install `.[voice]` for optional local transcription and embeddings. Missing iCloud audio must first hydrate on the Mac.

On the Mac: `.venv/bin/personal-context voice-memos-sync --config /absolute/private/apple.json`. On the archive host run `.venv/bin/python -m personal_context.voice_memos_worker process --db "$PERSONAL_CONTEXT_DB"`. Check `apple_voice_memo_status`, transcript coverage and original-audio availability separately.

Follow [Apple Voice Memos setup and sync](../../resources/voice_memo/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
apple_voice_memo_status() -> dict
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.voice_memos_mcp`. See [privacy and retention](../../PRIVACY.md).
