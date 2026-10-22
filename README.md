# Personal Context Bridge

A self-hosted MCP bridge for your own Apple, Canvas, Health, travel, and Obsidian
context. Search encrypted archives from an MCP client, check sync freshness, and
retrieve bounded records. Each person supplies their own accounts and devices.

Optional [Instagram Saved-video search and analysis](docs/INSTAGRAM-SAVED.md)
uses a Saved-only URL collector, separate anonymous downloads, local speech/OCR,
encrypted media storage and timestamped image tools. It is disabled by default.

Optional [Apple Voice Memos](docs/VOICE-MEMOS.md) adds full native/local transcripts,
encrypted audio, shared subscription-backed titles/summaries, and local hybrid
search. Collection and advanced processing are opt-in.

This repository contains reusable code and fictional tests. It ships no personal
archive, account credentials, installed app IDs, or maintainer deployment history.

## Try it with fictional data

Use Python 3.11+ on Linux for the archive server. With [uv](https://docs.astral.sh/uv/):

```sh
git clone https://github.com/jeremydevv/personal-context-bridge.git
cd personal-context-bridge
uv venv --python 3.11
uv pip install -e '.[mcp,messages,images]'
.venv/bin/personal-context-setup --demo --iphone
```

The setup command creates a random 32-byte key, encrypted databases, private source
templates, upload credentials, and `mcp.json` under
`~/.local/share/personal-context-bridge/runtime`. It refuses to overwrite an
existing installation or put runtime state inside a source checkout. `--iphone`
is optional; it creates empty Health/travel archives, not fictional health data.

Copy the generated `mcpServers` entries from that private `mcp.json` into your
MCP client's configuration. The file already contains absolute paths to this
installation's Python interpreter and private archive. Restart the client and
ask it to search for **fictional**. The demo returns three clearly fictional
Calendar, Reminder, and Notes records. Use a separate `--root` when setting up
real collection, so demo records do not mix with your context.

For pip, replace the two uv commands with `python3 -m venv .venv` and
`.venv/bin/pip install -e '.[mcp,messages,images]'`. On Ubuntu, install the matching
`python3-venv` package if venv creation is unavailable. There is no published PyPI
package yet; install from this repository.

## Connections

| Connection | Data available | Authentication / permission |
|---|---|---|
| Apple Calendar | Event titles, notes, timing, participants and source details | macOS Calendar permission through Apple PIM; SSH key for archive transfer |
| Apple Reminders | Lists, tasks, notes, dates and completion | macOS Reminders permission through Apple PIM; SSH key for transfer |
| Apple Contacts | Names, emails, phones, addresses and other contact fields | macOS Automation access to Contacts; SSH key for transfer |
| Apple Mail | Mailbox inventory, headers, recipient details and available bodies | Local Mail index via patched Apple PIM; Full Disk Access; SSH key for transfer |
| Apple Messages | Messages, participants, attachment metadata and optionally file bytes | Full Disk Access to the local Messages database/files; SSH key for transfer |
| Apple Notes | Titles, available bodies, folders and timestamps | macOS Automation access to Notes; SSH key for transfer |
| Apple Voice Memos | Full transcripts, source titles/dates, generated summaries and local semantic passages | Mac local Voice Memos/iCloud cache read access; existing SSH transport; shared ChatGPT-plan OAuth for summaries |
| Canvas | Student courses, assignments, submissions/grades, announcements, files, and Inbox conversations; optional PDF/DOCX text | User-provided Canvas API bearer token in a private local file |
| Apple Health | Selected HealthKit samples, workouts/routes, activity summaries and aggregates | HealthKit read permission in the PulsHealth iPhone app; bearer token for receiver uploads |
| OwnTracks | Location coordinates, timestamps and travel event metadata | iOS location permission; HTTP Basic authentication with a private generated password |
| Google Maps Timeline | Visits, activities and paths from an on-phone JSON export | User-provided export file; no live Google OAuth connection |
| Obsidian | Allowlisted vault files; optional revision-checked Markdown edits | Local filesystem/encrypted mount access; iCloud authentication belongs to your own sync setup |
| MCP client | Tool-selected records from your archives | Local stdio subprocess; remote access requires your own authenticated transport |

## Connect your sources

Follow [setup](docs/SETUP.md) for Mac-to-Linux collection, Canvas, iPhone receivers,
Timeline imports, Obsidian, scheduling, and backups. [MCP configuration examples](examples/mcp.example.json)
show the separate source servers. For ChatGPT web, follow the
[private tunnel guide](docs/CHATGPT.md). The archive works while collection devices are
asleep; check timestamps before assuming current data.

The Apple collectors need macOS. The archive/query service and iPhone receivers
are tested on Linux. On macOS, the `mcp` extra uses `sqlcipher3`, requiring a
working native SQLCipher build (for example Homebrew SQLCipher plus matching
compiler flags). Windows is not supported by the current Unix lock/mount code.
Image previews require the `images` extra and PDF text extraction requires
`pdftotext` (`poppler-utils` on Ubuntu). Locked Notes, absent Messages attachments,
and image-only PDFs may have no readable content.

## Privacy and writes

For opt-in native Calendar and Reminders editing, see
[direct MCP editing](docs/APPLE-PIM-EDITING.md): exact-ID updates/deletes,
calendar/list selection, alerts, driving estimates, real Urgent alarms and subtasks.

`set_apple_calendar_travel_time` edits the native travel duration without routing
or phone-location access. Supply a live inspected ID, occurrence start, revision,
and `duration_minutes` (0–10080 whole minutes; 0 clears). The initial adapter
supports timed, nonrecurring, non-detached events without attendees, with this-event
scope only. It verifies persisted seconds and preserves all other inspected
fields. It does not enable dynamic travel updates or guarantee notification delivery.

Archives use SQLCipher; binary attachments use authenticated AES-GCM encryption.
Keys and upload credentials are separate files created with mode 0600 in a
private directory. Keep a secure recovery copy of the key: losing it loses access
to your archive. Read [privacy and retention](docs/PRIVACY.md) before using real data.

The default MCP surfaces retrieve data. Refresh requests and Mail sending are
opt-in. Obsidian writes require explicit server configuration and revision checks.
Mail sending uses a separately configured sender/account and a worker with a
five-minute cancellation window. Tool annotations and descriptions do not enforce
human approval; configure your client to require approval for write operations.

Local storage does not mean the AI provider never sees your data: tool results
are sent to the client/model you connect. Do not expose the receiver ports directly
to the public internet. Supply an authenticated, encrypted network path for phone
uploads; the receiver processes deliberately bind to loopback.

## Development

```sh
uv pip install -e '.[mcp,messages,images,dev]'
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m unittest discover -s iphone/tests
.venv/bin/python iphone/tests/upstream_smoke_test.py
.venv/bin/python scripts/check_release.py
.venv/bin/python -m build
```

The Health HTTP smoke test uses synthetic upstream fixtures and temporary encrypted
storage. Device permissions and live account access are user-specific and are not
exercised by CI. See [CONTRIBUTING.md](CONTRIBUTING.md).

Original bridge code is [MIT licensed](LICENSE). Adapted PulsHealth components
retain [Apache-2.0 licensing](third_party/pulshealth/LICENSE); see [NOTICE](NOTICE).

### Native Calendar and Reminders creation

Optional chat tools queue approved creates on Ubuntu and deliver them to the Mac
when it is available. They use existing native calendars/lists and require
one-time macOS permissions. Writes are disabled by default. Jobs can be checked
or cancelled across chats; uncertain delivery is never automatically retried.
A Mac that is off cannot create an item or guarantee an on-time alert. See
[Mac queued writes setup](docs/SETUP.md#native-calendar-and-reminders-writes-through-a-mac)
for tools, native alarm behavior, and rollout requirements.
