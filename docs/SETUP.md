# Connect your own sources

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
PDF/DOCX text extraction. PDF extraction needs `pdftotext`; DOCX uses the standard
library. Scanned PDFs may return no text. On the archive machine, with the two
archive environment variables above:

```sh
.venv/bin/personal-context-canvas --config "$CONTEXT_RUNTIME/canvas.json" --db "$PERSONAL_CONTEXT_DB"
```

The collector reads student courses, submission/grade details included in
assignments, announcements, and file metadata. It follows complete pagination
before marking snapshots complete. API failures abort before ingest. File
extraction failures are recorded as unavailable. Canvas API tokens are sent only
to the configured origin; signed file redirects receive no token on another origin.
An empty course inventory retires that account's archived course-linked records.

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
mirroring/rotation; it expects `config.json` in `PERSONAL_CONTEXT_CONFIG_DIR`,
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
