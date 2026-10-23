# Unified data refresh and headless collection

Status: proposed for user approval; no coordinator deployed.

## Intent

Make refresh behavior consistent across every Personal Context MCP source. A
request must be traceable to its actual outcome without leaving unrelated GUI
apps open. Archived data stays readable while source devices are unavailable.
The user requested an MCP-wide fix, refresh tracking, and collection that is as
headless as practical. Implementation choices below are proposed builder calls.

## Approaches

1. **Recommended: shared coordinator and existing collectors.** Add a common
   job/receipt contract, source-specific dispatch, and lifecycle handling around
   the proven collection, encrypted spool, and ingestion paths. This addresses
   tracking and unnecessary app launches with bounded migration risk.
2. **Status aggregation alone.** Cheaper, but cannot tie accepted requests to
   completion and leaves broad Apple refreshes opening unrelated apps.
3. **Rewrite all source adapters.** Could remove more GUI dependencies, but
   private Apple formats, iCloud hydration and permissions make parity costly.
   Replace an individual adapter only after verifying equivalent source fields.

## Required outcomes

- All existing source surfaces expose a common freshness and refresh contract.
- Request one source without invoking unrelated source collection or GUI apps.
- Track accepted, waiting, running, partial, complete, failed and interrupted
  work with durable IDs and bounded retries. Device unavailability is visible.
- Distinguish job execution, source collection, acknowledged archive ingestion,
  upstream replica freshness, and generated-summary progress.
- Preserve apps open before collection. Restore collector-opened apps even when
  collection fails, except when doing so would interrupt user work.
- Prefer native APIs, read-only replicas and network APIs to GUI automation.
- Keep current source allowlists, credentials, archives and user permissions.

## Shared model

Use a durable Ubuntu-side refresh ledger. Store metadata only, not source bodies,
addresses, file paths or raw exception output. Store outside public checkouts,
owner-only, within the existing encrypted runtime state facilities.

A parent request has an opaque ID, requested sources, mode (recent/full), trigger
(manual/scheduled), creation time, and per-source child jobs. Each child records
its attempt ID, lease owner/expiry, heartbeat, phase, timestamps, sanitized error
code, retry time, collection coverage and acknowledged ingestion receipts.

Execution state and freshness are separate fields: `complete` means the selected
collection scopes were processed and all produced batches were acknowledged by
the archive. It does not mean the provider has no undiscovered data. `partial`
means at least one selected scope failed or deferred. Source age thresholds
produce fresh/stale/unknown independently of execution state. Empty successful
snapshots and unchanged data count as successful collection, not as new content.

Each run and batch carries a request/attempt ID through the existing spool and
SSH ingestion envelope. A valid acknowledgement is emitted after the archive
transaction commits and identifies the exact batch/attempt/scopes. Replay is
idempotent. Source collectors report failures and coverage explicitly. Never
infer completion solely from launchd/systemd acceptance or an unrelated later
source timestamp. Retain the previous successful baseline after failed attempts.

The coordinator persists queued intent before dispatch. A leased worker starts
fixed, configured commands only. Mac workers pull or receive bounded requests
through the existing SSH transport; credentials and native APIs remain on the
Mac. Waiting requests survive disconnection. Join equivalent active requests
without losing their IDs; serialize shared native resources across scheduled,
manual, full and fast collection. Bound lock waits, run time and output size.
After restart, reconcile expired leases as interrupted before safely retrying;
never leave a request permanently running because a worker disappeared.

## MCP contract

Proposed main tools: `request_data_refresh(sources, mode="recent")`,
`data_refresh_status(refresh_id)`, and `data_source_status(source="all")`.
Read-only status calls never initiate collection. Existing force-refresh tools
remain compatibility wrappers, returning the durable ID and truthful acceptance
state. Existing source status tools retain old fields and add the common status.
Main status/get-record compatibility paths expose the same information for
clients whose named-tool catalog has not refreshed.

Default source set is the configured, enabled collection set; reject unknown or
disabled sources. A combined request reports every requested source, including
unsupported refresh capabilities. Existing per-tool approval behavior remains;
no new provider, permission, login or device setup is silently enabled. A read
can warn about stale data but must not silently trigger a GUI-dependent refresh.

## Source inventory and headless policy

| Source | Existing collection | Planned behavior and honest limit |
| --- | --- | --- |
| Calendar, Reminders | Native Apple PIM APIs | Keep headless framework reads; source-only dispatch and per-scope ingestion receipts. |
| Contacts | Contacts.app/JXA snapshot | Implement a native Contacts-framework adapter; verify IDs, groups and every existing field against controlled fixtures. Do not fall back automatically on permission denial. Preserve automation as an explicitly reported fallback only where already authorized. |
| Messages, attachments | Local database/files | Keep headless reads; distinguish text collection from optional attachment hydration. |
| Notes | Notes.app/JXA | Background-only automation with shared lifecycle policy. A database-only replacement is deferred unless equivalent content can be proven. |
| Mail | Native app fetch and local replica | Reuse guarded background launch/cleanup. Replica quiescence is a bounded heuristic, not provider completion. Preserve user foreground use/composition and coordinate refresh ownership with sending without changing send behavior. |
| Voice Memos | Local database/audio/transcripts | Keep headless reads. Report missing local/iCloud audio independently; never claim hydration merely because metadata collection finished. |
| Canvas | Existing read-only API runner | Keep headless API and encrypted upload; report per-resource partial/unavailable coverage. |
| Obsidian | Existing guarded iCloud reconciliation | Preserve vault scopes, conflict protection and write semantics; distinguish remote reconciliation from local readable-file scan. |
| Saved videos | Saved-only GET plus separate anonymous processing | Keep strict Saved scope; track list collection, media and indexing phases separately. |
| Health | Phone upload and Ubuntu ingestion | Expose actual upload/sample freshness and receiver state. Server cannot force a phone capture; report waiting-for-device or unsupported remote refresh. |
| OwnTracks | Device-pushed location and server processing | Distinguish latest fix, receipt and processing. Server cannot force a new phone fix. |
| Google Timeline | Explicit import | Report import provenance and manual-import requirement; do not invent automatic refresh. |
| iCloud Drive | Read-only live access, authentication deferred | Report not connected/live-read capability. Refresh does not create an offline mirror or initiate authentication. |
| Generated summaries | Separate enrichment workers | Report backlog, processing success and source-version coverage separately from source refresh completion. |

App lifecycle receipts record only app name, initial state, collector ownership,
launch mode, final state and cleanup outcome. If user interaction or composition
prevents cleanup, report `preserved_for_user` rather than a cleanup success.
If a helper is necessary for OS permissions, use the existing authorized native
helper and report its capability; do not bypass macOS consent.

## Scheduling and deployment

Keep existing schedules initially. Scheduled and MCP-requested work emit the same
receipts and use the same per-source resource locks. Configure installed job
labels and executable paths explicitly rather than substituting public example
labels. Preserve private runtime transfer retries, timeouts, credentials and the
existing disabled Mac archive-backup policy.

Ship incrementally: ledger/protocol and source-only dispatch; Apple and Canvas
runner integration; other-source adapters and common status; Contacts native
parity; installed verification and compatibility tests. Deploy only verified
stages and retain originals for rollback. Do not claim deployment on an
unreachable Mac; Ubuntu and Mac verification are separate outcomes.

## Validation and acceptance

Fictional automated scenarios must cover queued offline recovery, concurrent
manual/scheduled runs, partial sources, unchanged/empty snapshots, ingestion
failure and replay, expired lease/crash restart, duplicate requests, cleanup
failure, and user-open apps. A later unrelated sync must not complete an earlier
request. Permission denial must not silently switch collector behavior.

On the actual installed system, verify one full request lifecycle and archive
readback per dispatchable source, plus one source-only Apple refresh that leaves
unrelated apps closed. Verify all-source reporting includes push-only/manual and
not-connected sources without falsely completing them. Native Contacts requires
field/ID parity and no Contacts.app launch. Confirm original schedules and Mac
backup opt-out remain intact. Verify backend tool registration independently of
client tool discovery, and bind CI claims to the published source commit.

## Open decisions

No user-only product decision is needed to prepare implementation: source scopes,
headless preference, tracking requirement and privacy constraints are established.
The recommended coordinator architecture and tool names are proposed here for
approval. Platform restrictions remain explicit delivery limits rather than
promises of completely headless provider synchronization.
