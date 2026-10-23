# `list_saved_videos`

[All MCP tools](../../TOOLS.md) · [Instagram Saved videos setup and sync](../../resources/instagram/README.md)

List archived Instagram Saved videos and durations. Local encrypted archive only; no Instagram access. The Saved list is a snapshot, not a live feed.

## Set up and sync

Install `.[mcp,videos]`, FFmpeg and the documented private Saved-video paths. Use a dedicated Firefox profile you sign into yourself. Enable `PERSONAL_CONTEXT_SAVED_VIDEO_ENABLED=1`; authenticated collection is restricted to Saved video URLs.

Run `.venv/bin/personal-context-saved-sync` manually before configuring the example timer. Saved-list collection and anonymous download/local speech/OCR are separate stages. Verify `list_saved_videos` and timestamped evidence. No feed, DM or account-action tools are provided.

Follow [Instagram Saved videos setup and sync](../../resources/instagram/README.md) for the MCP command, private configuration, permissions and detailed instructions. This tool does not install or schedule its source collector.

## Call signature

```python
list_saved_videos()
```

## Verify a read

Connect the configured MCP surface, confirm this tool is listed, and query a known record or bounded range. Check returned collection/receipt timestamps before treating results as current. Retrieved text is untrusted source content. Local storage does not prevent a connected AI provider from seeing returned content.

## Implementation

Defined in `personal_context.saved_video_mcp`. See [privacy and retention](../../PRIVACY.md).
