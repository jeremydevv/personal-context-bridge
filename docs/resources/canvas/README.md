# Canvas

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../SETUP.md#canvas)

## Set up this resource

Create your own institution-approved Canvas API token in a private mode-0600 file. Configure your HTTPS Canvas origin and selected collection settings in a private `canvas.json`; see the detailed guide for its schema.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

Run `.venv/bin/personal-context-canvas --config /absolute/private/canvas.json --db "$PERSONAL_CONTEXT_DB"`. Check `canvas_status` and a known course/module. Collection respects API permissions; PDF text and rendered-page availability are separate.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.canvas_mcp_server
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Tools

- [`canvas_inbox`](../../tools/canvas_inbox/README.md)
- [`canvas_module_items`](../../tools/canvas_module_items/README.md)
- [`canvas_modules`](../../tools/canvas_modules/README.md)
- [`canvas_pdf_info`](../../tools/canvas_pdf_info/README.md)
- [`canvas_search_explanations`](../../tools/canvas_search_explanations/README.md)
- [`canvas_status`](../../tools/canvas_status/README.md)
- [`canvas_summary_status`](../../tools/canvas_summary_status/README.md)
- [`force_refresh_canvas`](../../tools/force_refresh_canvas/README.md)
- [`get_canvas_explanation`](../../tools/get_canvas_explanation/README.md)
- [`get_canvas_record`](../../tools/get_canvas_record/README.md)
- [`list_canvas_records`](../../tools/list_canvas_records/README.md)
- [`read_canvas_file_text`](../../tools/read_canvas_file_text/README.md)
- [`search_canvas`](../../tools/search_canvas/README.md)
- [`upcoming_canvas_assignments`](../../tools/upcoming_canvas_assignments/README.md)
- [`view_canvas_pdf_page`](../../tools/view_canvas_pdf_page/README.md)
