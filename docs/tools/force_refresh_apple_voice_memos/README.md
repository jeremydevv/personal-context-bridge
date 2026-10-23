# `force_refresh_apple_voice_memos`

[All MCP tools](../../TOOLS.md) · [Apple Voice Memos setup and sync](../../resources/voice_memo/README.md)

Request the Mac's existing Apple sync job, including opted-in Voice Memos. Acceptance is not collection or iCloud download completion. Check apple_voice_memo_status for a later timestamp. Does not record, rename, delete or edit Apple memos.

## Set up and sync

Enable `all_voice_memos` in the private Mac configuration and configure the existing SSH transport. Install `.[voice]` for optional local transcription and embeddings. Missing iCloud audio must first hydrate on the Mac.

On the Mac: `.venv/bin/personal-context voice-memos-sync --config /absolute/private/apple.json`. On the archive host run `.venv/bin/python -m personal_context.voice_memos_worker process --db "$PERSONAL_CONTEXT_DB"`. Check `apple_voice_memo_status`, transcript coverage and original-audio availability separately.

Follow [Apple Voice Memos setup and sync](../../resources/voice_memo/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
force_refresh_apple_voice_memos() -> dict
```

## Enable and verify the action

This optional action requires its documented private configuration and client approval policy. Read the resource guide before enabling it. A refresh request reports acceptance; check a later source timestamp for completion. A queued native write needs a completed receipt and native readback. Do not automatically retry an uncertain write.

## Implementation

Defined in `personal_context.voice_memos_mcp`. See [privacy and retention](../../PRIVACY.md).
