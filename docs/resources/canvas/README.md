# Canvas

[Project](../../../README.md) · [All tools](../../TOOLS.md) · [Detailed setup](../../SETUP.md#canvas)

## Set up this resource

Choose the collection mode your institution permits. Both feed the same encrypted
archive and Canvas read tools; neither grants access beyond your account.

| Mode | When to use it | Setup |
| --- | --- | --- |
| API token | Your institution exposes and permits personal API-token access. | Store your own token in a private mode-0600 file and configure your HTTPS Canvas origin in private `canvas.json`; see [token setup](../../SETUP.md#api-token-collection). |
| Firefox browser session | Your institution does not expose personal API-token creation, but permits access through your signed-in Canvas session. | Use the existing [Firefox-backed collector](../../canvas-browser.md) on Ubuntu with your own private profile and configuration. No API token is created. |

The browser option uses structured API reads authenticated by your existing
session, not an autonomous login agent. Complete institutional SSO/MFA yourself.
It does not bypass institutional policy or permission restrictions, and an
expired session requires interactive sign-in again.

Start with the [private archive and client setup](../../SETUP.md#archive-server-and-mcp-client). Keep credentials, data, keys and filled configurations outside the checkout.

## Collect and verify

For token collection, run `.venv/bin/personal-context-canvas --config /absolute/private/canvas.json --db "$PERSONAL_CONTEXT_DB"`.
For browser collection, follow the [private configuration and run command](../../canvas-browser.md#private-configuration),
then check `canvas_browser_status` for the terminal result. For either mode,
check `canvas_status`, the selected account and a known course/module. Collection
respects account permissions; PDF text and rendered-page availability are separate.
Queued or running is not finished, and a partial result is not complete coverage.

After manual verification, choose your own schedule from [scheduling](../../SETUP.md#scheduling-backups-and-optional-actions). Cloning this repository does not install a collector or enable timers.

## Connect the MCP surface

Use your installation’s absolute interpreter path and this module in the MCP client:

```sh
/absolute/project/.venv/bin/python -m personal_context.canvas_mcp_server
```

Configure the environment from the detailed setup guide. Standard archive surfaces use `PERSONAL_CONTEXT_DB` and `PERSONAL_CONTEXT_KEY_FILE`; Health/travel and Obsidian use their own documented environment. Prefer the generated private `mcp.json` or [configuration example](../../../examples/mcp.example.json). The stdio command speaks JSON-RPC to a client. For ChatGPT web, use [your own authenticated tunnel](../../CHATGPT.md).

## Browser-backed collection

An existing authenticated Firefox session can collect a separately configured
Canvas account on Ubuntu, without the Mac. See [browser refresh](../../tools/refresh_canvas_browser/README.md)
for the 30-minute service, locking, retries and login status. Existing connector
catalogs can use `force_refresh_canvas(account="<configured account>")`; omit
`account` only for Mac collection. No additional tunnel is required when the main
Personal Context server already exposes Canvas.

## Optional generated explanations

The public distribution does **not** include the optional `summary_mcp` backend.
`canvas_summary_status`, `canvas_search_explanations` and `get_canvas_explanation`
remain discoverable for compatibility, but return `available: false` with
`state: unsupported_capability` when that backend is absent. This is not an
empty search, a missing source record, or a Wi-Fi pause; configuration flags do
not install the backend. There is no public installation procedure for it.
Use `search_canvas`, `list_canvas_records` and `get_canvas_record` to retrieve
original evidence. A client can explain that evidence without claiming that
stored generated explanations exist.

## Tools

- [`canvas_browser_status`](../../tools/canvas_browser_status/README.md)
- [`refresh_canvas_browser`](../../tools/refresh_canvas_browser/README.md)

- [`canvas_grades`](../../tools/canvas_grades/README.md)
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
