# Instagram Saved videos

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../INSTAGRAM-SAVED.md)

## Set up this resource

Install `.[mcp,videos]`, FFmpeg and the documented private Saved-video paths. Use a dedicated Firefox profile you sign into yourself. Enable `PERSONAL_CONTEXT_SAVED_VIDEO_ENABLED=1`; authenticated collection is restricted to Saved video URLs.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

Run `.venv/bin/personal-context-saved-sync` manually before configuring the example timer. Saved-list collection and anonymous download/local speech/OCR are separate stages. Verify `list_saved_videos` and timestamped evidence. No feed, DM or account-action tools are provided.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.mcp_server
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Tools

- [`get_video_evidence`](../../tools/get_video_evidence/README.md)
- [`get_video_frame`](../../tools/get_video_frame/README.md)
- [`get_video_storyboard`](../../tools/get_video_storyboard/README.md)
- [`list_saved_videos`](../../tools/list_saved_videos/README.md)
- [`search_saved_videos`](../../tools/search_saved_videos/README.md)
