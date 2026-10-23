# Apple Voice Memos

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../VOICE-MEMOS.md)

## Set up this resource

Enable `all_voice_memos` in the private Mac configuration and configure the existing SSH transport. Install `.[voice]` for optional local transcription and embeddings. Missing iCloud audio must first hydrate on the Mac.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

On the Mac: `.venv/bin/personal-context voice-memos-sync --config /absolute/private/apple.json`. On the archive host run `.venv/bin/python -m personal_context.voice_memos_worker process --db "$PERSONAL_CONTEXT_DB"`. Check `apple_voice_memo_status`, transcript coverage and original-audio availability separately.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.source_mcp_server --source voice_memo
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Tools

- [`apple_voice_memo_status`](../../tools/apple_voice_memo_status/README.md)
- [`apple_voice_memo_timeline`](../../tools/apple_voice_memo_timeline/README.md)
- [`force_refresh_apple_voice_memos`](../../tools/force_refresh_apple_voice_memos/README.md)
- [`get_apple_voice_memo_record`](../../tools/get_apple_voice_memo_record/README.md)
- [`read_apple_voice_memo_transcript`](../../tools/read_apple_voice_memo_transcript/README.md)
- [`search_apple_voice_memo`](../../tools/search_apple_voice_memo/README.md)
