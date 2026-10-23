# Connect your own sources

Start with the [fictional quickstart](../README.md#quickstart), then choose a
[resource-specific README](../README.md#pick-your-sources). For an individual call,
use the [linked MCP tool directory](TOOLS.md). Each tool has its own README and
links back to the source collection instructions.

## Setup checklist

1. Initialize a private archive outside the checkout; keep demo and real roots separate.
2. Connect one source, with its own permissions and private credentials.
3. Run collection manually and verify a known record plus its collection timestamp.
4. Add the generated MCP configuration to your client and check tool discovery.
5. Enable your own schedule only after the manual path works.
6. Configure optional write workers separately and require client approval.

## Archive server and MCP client

Clone the repository and install `.[mcp,messages,images]` as in the README. Run
`personal-context-setup` without `--demo` for real collection. Optionally use
`--root /absolute/private/directory --iphone`. All commands below assume:

```sh
CONTEXT_RUNTIME="$HOME/.local/share/personal-context-bridge/runtime"
export PERSONAL_CONTEXT_DB="$CONTEXT_RUNTIME/context.sqlite3"
export PERSONAL_CONTEXT_KEY_FILE="$CONTEXT_RUNTIME/archive.key"
```

Run `.venv/bin/personal-context status --db "$PERSONAL_CONTEXT_DB"` to inspect
sync timestamps. Run `.venv/bin/python -m personal_context.mcp_server` only from
an MCP client; it speaks JSON-RPC on stdin/stdout, not a web page. Configure the
client with the generated private `mcp.json`. An existing installation's setup
cannot be overwritten; keep its key and use a different runtime directory for demos.

## Apple collection on a Mac

The archive server can be the Mac or a Linux machine reachable through SSH.
The bridge's Apple collector transfers over SSH to the configured archive host.
On Linux, the SQLCipher wheel is supplied by the `mcp` extra. On a Mac hosting
its own archive, build the `sqlcipher3` binding against your installed SQLCipher.
A Mac that only collects/transfers records can install `.[messages]` without
SQLCipher or the MCP SDK.

1. Install Python 3.11+, Git, and the Xcode/Swift toolchain on the Mac. Clone this
   repository and install it into `.venv` with `uv pip install -e '.[messages]'`.
2. Install the [Apple PIM tools](https://github.com/omarshahine/apple-pim). This
   bridge's Mail patch targets commit `4e155fc5a393c11fab8853565211422d02562a0a`.
   From a separate Apple PIM checkout, checkout that commit and run
   `./setup.sh --install`. Add `~/.local/bin` to PATH. Grant the helper Calendar
   and Reminders permissions in macOS System Settings when prompted.
3. For Mail, apply this repository's
   `third_party/apple-pim/apple-pim-mail-local-ids.patch` to that clean pinned
   checkout, then run `cd swift && swift build -c release --product mail-cli`.
   Copy `swift/.build/release/mail-cli` to
   `~/.local/share/personal-context-bridge/bin/mail-cli` (create the directory).
   Grant Full Disk Access to the process reading Mail's local index.
4. Grant Automation access to Contacts and Notes for their snapshot scripts.
   Grant Full Disk Access to the terminal/interpreter used for Messages collection.
   These permissions cannot be supplied by a repository clone.
5. Configure a trusted SSH alias such as `archive-server` on the Mac. Provision
   your SSH key and verify the server's host key through your normal SSH setup.
   The remote account must own the private archive directory. Clone/install
   this project there with its interpreter at `<remote_project>/.venv/bin/python`.
6. Copy `examples/apple.example.json` to a private Mac directory. Set
   `remote_project` to the absolute remote checkout path and `remote_data_dir`
   to the absolute remote private directory created by setup. Set
   `PERSONAL_CONTEXT_REMOTE_KEY_FILE` on the Mac to the archive server's absolute
   `archive.key` path. That variable configures remote ingest; it does not print
   or copy the key. Select only the sources you want and choose the date range.

Example manual collection, from the Mac checkout:

```sh
export PERSONAL_CONTEXT_REMOTE_KEY_FILE=/absolute/server/runtime/archive.key
.venv/bin/personal-context sync --config /absolute/private/apple.json
.venv/bin/personal-context contacts-sync --config /absolute/private/apple.json
.venv/bin/personal-context messages-sync --config /absolute/private/apple.json
.venv/bin/personal-context notes-sync --config /absolute/private/apple.json
.venv/bin/personal-context mail-sync --config /absolute/private/apple.json
```

`sync` collects Calendar/Reminders. Other commands require the corresponding
`all_contacts`, `all_messages`, `all_notes`, or `all_mailboxes`/`mailbox_urls`
settings. `calendar-cli list` and `reminder-cli lists` show the IDs you can
allowlist instead of collecting all visible calendars/lists.

Messages file bytes are a separate opt-in transfer:

```sh
.venv/bin/personal-context attachment-sync --config /absolute/private/apple.json --limit 50
```

Missing originals stay unavailable. Mail exports refuse incomplete snapshots or
mailboxes at the current 50,000-record cap; narrow the mailbox scope if needed.
Retry spools contain plaintext source batches on the Mac, protected by private
permissions. Use FileVault and keep those spools outside source repositories.

## Canvas

Create a personal API access token through your institution's Canvas account
settings if that option is enabled. Institution policy may prevent token creation.
This portable collector uses a bearer token, not browser-cookie extraction.
Keep the token in the `token_file` named by your private `canvas.json`; create it
with mode 0600 and never put the token in shell arguments or Git.

Set `base_url` to your institution's HTTPS Canvas origin and `account` to a short
label of your choice. Set `download_files` to true only if you want bounded
PDF/DOCX text extraction and retention of original PDFs (up to 16 MiB per file).
Originals are stored separately from text in the encrypted archive; they are not
included in search or record responses. PDF extraction needs `pdftotext`; DOCX
uses the standard library. Text extraction omits embedded images and vector
graphs, even when the rest of a PDF has readable text. Use `canvas_pdf_info` for
the page count and `view_canvas_pdf_page(record_id, page=1)` for an actual page
image. Viewing requires `pdfinfo` and `pdftoppm` on the archive server (install
`poppler-utils` on Ubuntu or `poppler` on macOS). Old text-only records need a
new collection with `download_files` enabled. Scanned PDFs remain viewable even
when text extraction returns no text or fails. On the archive machine, with the two
archive environment variables above:

```sh
.venv/bin/personal-context-canvas --config "$CONTEXT_RUNTIME/canvas.json" --db "$PERSONAL_CONTEXT_DB"
```

The collector reads student courses, submission/grade details included in
assignments, announcements, file metadata, and Canvas Inbox conversations
(including archived conversations). Conversation message bodies and participant
names are stored in the encrypted archive. Conversation detail requests explicitly
disable Canvas's automatic mark-as-read behavior, so collection does not change
Inbox state. Use `canvas_inbox` to list threads, `search_canvas` to search them,
and `get_canvas_record` with `kind="conversation"` to read a full thread. This is
Canvas Inbox data, separate from Apple Mail. It follows complete pagination
before marking snapshots complete. Unexpected API failures abort before ingest. File
extraction failures are recorded as unavailable. Canvas API tokens are sent only
to the configured origin; signed file redirects receive no token on another origin.
An empty course inventory retires that account's archived course-linked records;
inbox and archived conversation snapshots are tracked separately.

Module collection reads `/courses/:course_id/modules` and each module's separately
paginated `/items` endpoint; it does not rely on optional inline item arrays.
`canvas_modules(course_record_id)` lists modules in course order;
`canvas_module_items(module_record_id)` lists items in module order. Both accept
`limit` and `offset` and return totals, scope sync time and collection status.
States, prerequisites, indentation, completion requirements and content details
are retained. These reads do not mark items done, record progress, or launch tools.

Linked Canvas Pages are collected once per course with original HTML and extracted
text. Use `search_canvas(kind="page")` or `get_canvas_record(kind="page", record_id=...)`.
Items include `linked_record_id` for archived Pages, Assignments and Files. Quiz,
Discussion, ExternalUrl and ExternalTool items retain metadata and links; their
content is not fetched by module collection, and external URLs/tools are never
followed. Linked file availability still depends on existing file collection.

A module/items HTTP 403 or 404 marks that course's `payload.module_collection`
unavailable and omits new module snapshots for it, preserving earlier snapshots
with their earlier timestamps. It does not claim an empty course. Linked page
403/404 responses are explicit unavailable placeholders without old page text;
locked pages retain the API's lock information. Module, item and page counts and
sync times are reported separately in `canvas_status`, alongside the number of
courses with unavailable module access. Successful empty snapshots retire removed
modules, items and linked pages; course removal retires all three kinds.

The original Mac deployment's separate Canvas collector is not distributed here;
this portable collector provides the same archive record kinds and MCP queries.

## Health and OwnTracks

Initialize with `--iphone`. Setup writes `receivers.json` with paths to the empty
encrypted archives and generated private upload credentials. It also adds Health
and travel entries to `mcp.json`. Receivers are independent of MCP readers.

Use the following environment variables in a private service configuration.
Paths are in `receivers.json`; do not commit the filled configuration:

| Receiver | Command | Required environment |
|---|---|---|
| Health | `.venv/bin/python -m iphone_context.health_receiver` | `PULS_DB`, `PULS_KEY_FILE`, `PULS_TOKEN_FILE`; optional `PULS_PORT` (8787) |
| OwnTracks | `.venv/bin/python -m iphone_context.location_receiver` | `OWNTRACKS_DB`, `OWNTRACKS_KEY_FILE`, `OWNTRACKS_CREDENTIAL_FILE`; optional `OWNTRACKS_PORT` (8788), `OWNTRACKS_USERNAME` (iphone) |

Both listeners bind to `127.0.0.1`. Provide an HTTPS reverse proxy or a private
TLS network route that your phone can reach. Keep uploads authenticated; do not
publish either raw HTTP receiver port. The public repository is source distribution,
not a hosted service or a tunnel tied to the maintainer's account.

In [PulsHealth](https://github.com/PulsHealth/pulshealth), grant selected HealthKit
read permissions, configure your endpoint for Puls Sync Protocol v1, and use the
private `health.token` contents as the bearer token. The batch route is
`/v1/batches`; capabilities are at `/v1/capabilities`. The default synthetic UUID
is only a fallback protocol identity; supply your own stable `X-User-ID` when
supported. This archive is for one person's data, not multiple independent tenants.

In [OwnTracks](https://owntracks.org/booklet/guide/connection/), choose HTTP mode,
configure your HTTPS endpoint ending in `/pub`, use your configured username and
the private `owntracks.password` contents, and grant the location permissions you
want. Background collection and delivery depend on iOS scheduling and permissions.
Neither bridge can force fresh phone uploads; check receipt times.

## Google Maps Timeline

Export your on-phone Timeline JSON. The importer accepts the `semanticSegments`
object or corresponding segment array, not every Google Takeout schema.
Read it through stdin to avoid making another plaintext copy:

```sh
export IPHONE_ARCHIVE_KEY_FILE="$CONTEXT_RUNTIME/archive.key"
export IPHONE_TRAVEL_DB="$CONTEXT_RUNTIME/travel.sqlite3"
.venv/bin/python -m iphone_context.timeline_import --db "$IPHONE_TRAVEL_DB" --key-file "$IPHONE_ARCHIVE_KEY_FILE" < /private/path/timeline-export.json
```

The importer bounds input size, streams records, deduplicates segments, and stores
exact coordinates in the encrypted travel archive. No Google password or OAuth
credential is used by this importer. Preserve/protect or delete your original
export deliberately; importing it does not remove the original.

## Obsidian

Mount/unlock your encrypted vault root, then configure
`personal_context.obsidian_mcp_server` with `OBSIDIAN_VAULT_ROOT` and a comma-separated
`OBSIDIAN_VAULTS` allowlist. You must supply your own vault names. By default the
root must be a mount point; set `OBSIDIAN_REQUIRE_MOUNT=0` only when deliberately
using a local directory instead. This bridge does not encrypt that directory.

Reads are the default. Set `OBSIDIAN_WRITE_ENABLED=1` only to permit note changes.
Edits/deletes require the current SHA-256 revision and keep previous content in
`.mcp-backups` under that vault root. Enable per-call write approval in the client.
The optional `scripts/obsidian_icloud_sync.sh` preserves bidirectional rclone
reconciliation without personal paths or vault names. Install rclone, configure
your own remote to the Mac's authenticated iCloud directory (or your own iCloud
backend), and provide `OBSIDIAN_ICLOUD_BASE`, `OBSIDIAN_REMOTE_BACKUP_BASE`,
`OBSIDIAN_VAULTS`, `OBSIDIAN_VAULT_ROOT`, and `RCLONE_BIN`. The local root must be
an encrypted mount. Start with `--initialize` only when both copies match; then
inspect `--dry-run` before enabling scheduled `--run` reconciliation. It shares
the MCP write lock, retains overwritten files, limits deletions and records
successful sync freshness. Your rclone configuration/credentials remain private.
No existing iCloud account or production sync service is installed by cloning.

## Scheduling, backups, and optional actions

Start with manual collection. After verifying permissions, use a Mac LaunchAgent
or a systemd user timer to run the explicit commands above, using absolute paths.
The sample [LaunchAgent](../examples/apple-sync.plist.example) and
[systemd service](../examples/archive-health.service.example) need your paths and
private environment files. Use your selected schedule; no scheduler is installed
by cloning. Disable/stop collectors before moving paths or keys.

On the archive server, a verified encrypted backup can be created with:

```sh
.venv/bin/personal-context backup --db "$PERSONAL_CONTEXT_DB" --output /private/backup/context.sqlite3
.venv/bin/python -m iphone_context.archive_backup --source health --data-dir "$CONTEXT_RUNTIME" --key-file "$PERSONAL_CONTEXT_KEY_FILE"
.venv/bin/python -m iphone_context.archive_backup --source travel --data-dir "$CONTEXT_RUNTIME" --key-file "$PERSONAL_CONTEXT_KEY_FILE"
```

Back up encrypted attachment blobs as well as the database and protect a separate
recovery copy of your key. Restore into an isolated private directory and verify
queries before replacing an archive. iPhone snapshots retain seven copies by
default. The optional Mac `personal_context.sync_runner` adds encrypted backup
mirroring/rotation. Set `"mac_backups_enabled": false` in the Mac
`config.json` to keep both full and fast collection uploading into the archive
server without database or attachment backups to the Mac. Existing configurations
default to backup mirroring when this setting is omitted. The runner expects
`config.json` in `PERSONAL_CONTEXT_CONFIG_DIR`,
`archive.key` there or at `PERSONAL_CONTEXT_KEY_FILE`, and remote key provision
paths configured through `PERSONAL_CONTEXT_REMOTE_KEY_FILE`. Provide private
runtime storage for the remote key; automatic temporary key provisioning requires
the same key as the initialized archive. Use `PERSONAL_CONTEXT_DATA_DIR` for its
private queues/backups. Optional TPM sealing requires systemd/TPM access; the
provisioner is advanced tooling, not required for initial setup.

Set `PERSONAL_CONTEXT_REFRESH_ENABLED=1` only after installing your own jobs:
`org.personalcontext.personal-context-fast-sync`,
`org.personalcontext.personal-context-canvas-sync`, and
`org.personalcontext.personal-context-message-refresh`. Configure the corresponding
SSH refresh targets (`PERSONAL_CONTEXT_REFRESH_TARGET`,
`PERSONAL_CONTEXT_MESSAGE_REFRESH_TARGET`). Refresh acceptance is not sync completion.

Mail sending is separate from archive retrieval. To enable its source-server
tools, set `PERSONAL_CONTEXT_MAIL_SEND_ENABLED=1`, `PERSONAL_CONTEXT_MAIL_FROM`,
`PERSONAL_CONTEXT_MAIL_ACCOUNT`, and `PERSONAL_CONTEXT_MAIL_SEND_TARGET`. Run
`personal_context.mail_send --process-due` in a separate scheduled worker with
those same settings and the private archive key. Use a dedicated outbox path
through `PERSONAL_CONTEXT_MAIL_OUTBOX_DB`. Each message requires client-enforced
human approval, has a five-minute hold, and can be cancelled while queued.
Ambiguous submission outcomes are not automatically retried. Do not change the
sender/account with pending messages; finish or cancel the outbox first.

Local generated daily summaries are optional. The episode builder defaults to
loopback Ollama at port 11434, accepts only that local endpoint, and preserves
source citations. Generated summaries are unverified; confirm important details
against the source records. No external model key is included.

## Native Calendar and Reminders writes through a Mac

Ubuntu stores approved creates in a SQLCipher outbox and delivers them over SSH
when the Mac is awake. Existing Apple accounts, calendars, and lists are used.
There is no new calendar/account to add on the phone. Calendar and Reminders
account sync and notifications remain Apple's responsibility.

### One-time Mac setup

1. Install the pinned Apple PIM revision documented above. Its `calendar-cli`
   and `reminder-cli` must support `auth-status`, `config show/init`, and `create`
   including the Reminder due-alert option. Install this package with Python
   3.11+ on the Mac; the receiver uses only its standard library.
2. From a **local Terminal on the Mac**, run `calendar-cli list` and
   `reminder-cli lists`. Grant full Calendar and Reminders access when prompted.
   The SSH process must also report `authorized` for both via `auth-status`.
   Terminal permission alone may not cover a headless SSH process. If macOS
   requests a different responsible application, authorize it locally or use an
   authorized app wrapper; do not bypass TCC or claim headless permission works
   without checking it.
3. Merge the Calendar/Reminders sections of
   `examples/mac-pim-executor.example.json` into the Mac's private Apple PIM
   configuration (`~/.config/apple-pim/config.json`). Keep both domains in `all`
   mode. Preserve unrelated configuration. Existing `default_calendar` and
   `default_reminder_list` are respected; otherwise the existing system defaults
   are used, selected by EventKit even if several accounts share the same name.
   Explicit names must be unique; IDs resolve duplicate names. Missing,
   ambiguous, or read-only destinations fail before create. No containers are
   ever created by this receiver. Broad writer access does not change which
   sources the separate archive collector reads.
4. Install a private fixed executable, for example `/private/bin/apple-write-receiver`:

   ```sh
   #!/bin/sh
   export PERSONAL_CONTEXT_APPLE_RECEIPTS_DB=/private/runtime/receipts.sqlite3
   export PERSONAL_CONTEXT_CALENDAR_CLI=/absolute/apple-pim/calendar-cli
   export PERSONAL_CONTEXT_REMINDER_CLI=/absolute/apple-pim/reminder-cli
   exec /absolute/project/.venv/bin/python -m personal_context.mac_pim_executor "$@"
   ```

   If using the upstream authorized Apple PIM Helper app, add
   `export PERSONAL_CONTEXT_APPLE_PIM_HELPER="/absolute/Apple PIM Helper.app"`
   to this executable. The receiver launches it through Launch Services with
   literal arguments and private temporary output files. It must already have
   Calendar and Reminders permissions. Its CLI directory must match the installed
   binaries (the helper defaults to `~/.local/bin`). Check health through this
   same receiver; direct CLI authorization may differ from the app's.

   Keep its config, runtime directory and receipt journal private. The journal
   stores job IDs, hashes and safe receipts, never titles or notes. It must be
   retained across receiver updates. Do not remove it to retry an uncertain job.
   Test `apple-write-receiver --health` over the **same SSH identity** Ubuntu uses.
   It must return `{"ready": true}`. This health check does not prompt for access.
   Prefer a dedicated SSH key restricted to this receiver (with a fixed forced
   command wrapper accepting only `--health` and `--apply-stdin`), no forwarding,
   no PTY. Keep its host key pinned in Ubuntu's known_hosts.

### Ubuntu worker and chat tools

Copy `examples/apple-writes.env.example` outside the source checkout, mode 0600,
and set the actual fixed SSH target and absolute receiver executable. Use the
same `PERSONAL_CONTEXT_KEY_FILE` and `PERSONAL_CONTEXT_APPLE_WRITE_DB` for both
MCP processes and the worker. The key must be a private, nonsymlink 32-byte file.
Keep the DB in a private runtime directory, outside source control.

Install the example user systemd service and timer as
`personal-context-apple-write-worker.service` and `.timer`, replacing paths. Add
your key-unlock service dependency and `ConditionPathExists` if the key is only
available after login. Run `systemctl --user daemon-reload` and
`systemctl --user enable --now personal-context-apple-write-worker.timer`.
The timer checks every minute; a process lock prevents overlapping workers.

With tools still disabled, verify synthetic creates through the receiver into
existing destinations, then cancellation, identical request retries, offline
preflight and ambiguous delivery handling. Test notification behavior on your
actual devices. Only then set `PERSONAL_CONTEXT_APPLE_WRITE_ENABLED=1` in both
Calendar and Reminders MCP environments and restart/reconnect those surfaces.
Invalid optional write configuration leaves archive reads available.

Available tools:

- Calendar: `queue_apple_calendar_event` (title, exact start/end, notes, optional
  alarm and existing calendar).
- Reminders: `queue_apple_reminder` (title, optional exact due time, notes, optional
  alarm and existing list).
- Both: `apple_write_job_status`, `pending_apple_write_jobs`, and
  `cancel_apple_write_job`. These access the same queue across chats.

Approve the exact fields in chat; no manual action is needed per item afterward.
Dates require ISO-8601 with seconds and an offset, such as
`2026-11-01T15:00:00-05:00`. Native Reminders has minute precision; reminder
due timestamps must have seconds `00` and no fractional seconds. Repeated local
hours during daylight-saving fallback are rejected before creation because the
pinned Reminder CLI cannot preserve which occurrence was approved. Use a new
request key for each intended new item and
reuse it only for an identical retry. Changed content under an existing key
fails. The host's tool approval policy must allow the queue call; annotations
and tool descriptions do not replace that host policy.

`queued` means saved on Ubuntu, not written into Apple. `completed` requires a
matching Mac receipt with an item ID. An offline preflight leaves the job queued;
a timeout, disconnect, or invalid receipt after delivery starts produces
`needs_review` and is never retried automatically. A worker crash likewise leaves
uncertain jobs for review. A cancelled queued job is never dispatched. Once it
is delivering it cannot be cancelled by this queue. Investigate `needs_review`
against the native app and Mac receipt journal before requesting a new create.

Timed Reminders receive the native due-time alert by default. A positive early
alarm shifts the time Reminders **displays and fires** to the earlier time; it is
not an extra alert alongside a later displayed due time. The receipt returns
`alert_at`, `late`, `alert_late`, and a safe `earlier_alarm_display` warning.
If the Mac was offline, the approved original due time is retained. Creation
and an item ID do not prove sync to the phone or delivery of a notification.
These tools create items only; edit/delete/complete and list/calendar management
are outside this release.
