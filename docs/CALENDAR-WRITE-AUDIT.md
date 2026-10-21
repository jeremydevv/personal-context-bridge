# Calendar write repair and coverage audit

Source audit and non-mutating validation: 2026-10-20. This is a source repair,
not a deployment or a claim of successful writes to every account/calendar.
No live event, invitation, calendar account, credential or permission was changed.

## Reproduced defect

An unsaved `EKEvent` reproduced `invalid_fields` with a valid local-midnight,
exclusive-next-day all-day request. Setting `isAllDay` changes EventKit's end
from exclusive midnight to the last second of the previous day and clears its
timezone. Setting a timezone after that can clear the all-day flag. The former
adapter applied the mode and then rejected the provider's changed boundary.

The adapter now validates exclusive boundaries before setting the final mode,
normalizes EventKit's inclusive final-second representation on inspection and
verification, and preserves all-day mode during partial date edits. Fractional
ISO timestamps accepted by Python are also accepted by Swift. Foreign-zone
floating all-day dates fail explicitly; they are not silently shifted to the
Mac timezone. Timed events retain their explicit timezone support.

## Coverage matrix

“Unsaved” means real EventKit objects with no authorization, store query, save,
or removal. “Mock” means fictional local state/transport, not provider behavior.
Existing test names below are discoverable under `tests/`.

| Surface/fields | Implementation and validation | Limits / remaining evidence |
| --- | --- | --- |
| Archived search, get, upcoming, source freshness | Existing source MCP/QueryService synthetic integration suite | Archive collection time is not live state; no new per-calendar query filter |
| Native exact event inspection | Exact ID + occurrence timestamp; record and revision | Existing deployed reads reported successful; complete record depends on native metadata helper |
| Existing calendar inventory and selection | Exact IDs preferred; unique name/default selection; Python receiver tests cover duplicate names, configured/system defaults | Account permission determines writability; no calendar/account creation tool |
| Read-only/subscribed calendars | Native source and destination writability guards remain | No grants changed; subscribed calendars cannot become writable through this adapter |
| Create/update/delete | Existing queue/worker/receiver tests: validation, literal transport, offline queue, receipt replay, conflicts, cancellation, uncertain-write handling | No live create/update/delete run in this repair; persistence still requires separate authorization |
| Title, notes, URL, location and explicit clearing | Python validation + unsaved native setters/clears | HTTP(S) URL without credentials only; provider normalization requires readback |
| Start/end, timezone | Unsaved timed and all-day cases; fractional timestamps; strict offset parsing | DST instant must be explicit; events must end after start |
| All-day and DST | Unsaved local-midnight create/update, spring 23-hour and fall 25-hour days, decoded JSON roundtrip | Floating all-day days use Mac local timezone; other zones fail before save |
| Alerts | Up to five distinct 0–10080 minute offsets; explicit clearing; Python and unsaved native tests | Ordinary relative start alarms only; no separate email/audio alarm model |
| Availability | busy/free/tentative/unavailable mapping; new pre-save supported-mask guard and inventory `availability_mask`; unsupported unsaved-calendar test | Depends on target calendar. No unsupported value is silently accepted |
| Recurrence replacement/clear | Frequency/interval/count/until and optional distinct weekly `weekdays`; Python and unsaved replacement/removal tests | Replacement can seed weekly weekday names but cannot express ordinal weekday/monthday/year/etc. selectors; use end-only editing to retain an existing complex rule |
| End Repeat | `changes.recurrence_end={date:'YYYY-MM-DD',timezone:'IANA'}` only, explicit future scope, fresh revision; Python queue/receiver/MCP tests; unsaved Tue–Fri and Monday native rules | Only a non-detached existing recurring event; no simultaneous edits; inclusive date; four-year/10000-event/8-MiB snapshot bounds |
| Existing selectors and ordinary occurrences | End-only changes mutate `recurrenceEnd` on existing rules, never reconstruct/remove/add them; native rule-record comparison and unchanged start/end tests | Rule persistence across a provider save is not proven by unsaved tests |
| Deleted and edited recurrence exceptions | Production snapshots compare actual occurrences before/after end-only save, including text, timing, calendar, alarms, availability and attendees. Unsaved mock storage tests apply the real end-only updater, compare snapshots, and detect a resurrected missing occurrence/changed exception | Mock exceptions are not persisted detached EventKit records. A mismatch after saving becomes needs_review; no automatic retry/rollback. Provider exception preservation needs separately approved persistence/readback tests |
| This/future occurrence scope | Existing explicit validation and native EKSpan dispatch | No implicit series-wide scope; end-only requires future; earlier occurrences are outside its selected scope |
| Driving/travel duration | Existing route-age/coordinate validation tests; native guarded travel setter and post-save verification | Dedicated tool/automatic routing only, requires fresh phone origin and Maps; no continuous travel updater; no real route request made here |
| Attendee edits | Existing dedicated structured tools, strict address/recipient validation and invitation-consent tests; guarded native selectors | Explicit delivery consent and organizer/account support required. No invitation or attendee save tested here |
| Ordinary edits/deletes with attendees | New native consent gate; explicit top-level `allow_invitation_delivery` on update/delete, strict Python/MCP validation; unsaved gate tests | These actions may notify existing participants; consent is per action, not a broad permission grant |
| Attachments | Existing PNG/JPEG/PDF hash/size/filename validation tests; dedicated native security-scoped access/readback code | Calendar/account/native-selector support required; 2 MiB/file, 4 MiB/batch, max five; no new live attachment test |
| Queue idempotency and write safety | Exact revision, request-key conflicts, receipt replay, pre-write failure vs post-write uncertainty tested with temporary encrypted storage and mock native results | A queued job is never evidence of a completed native change |
| MCP advertisement | Tests check typed end-only field, consent parameter, capability constraints and source separation | Runtime deployment and ChatGPT connection refresh/discovery still required |

Calendar color/account ownership, invitation delivery guarantees, arbitrary
RRULE replacement selectors, direct exception editing, attachment types beyond
PNG/JPEG/PDF, and continuous driving updates are not implemented by this API.
Private native selectors are capability-gated, not universal account support.

## Test commands

- `python -m unittest discover -s tests`
- `scripts/test_apple_pim_native.sh` on macOS: compiles the production functions
  with a separate test entry point. It never calls the production authorization,
  lookup, save or remove path.
- `scripts/build_apple_pim_native.sh /absolute/private/temporary/output` on macOS:
  compilation only; no app/account changes. The repair was built in a temporary
  directory and removed after testing.
- `python -m build` and `python scripts/check_release.py --history`.

## Deployment proposal (not executed)

Deployment needs explicit authorization for this concrete scope:

1. Pause the existing Ubuntu Apple write-worker timer and wait for any in-flight
   delivery to finish. Inspect pending/needs_review states without replaying any
   failed or uncertain jobs. Keep the 14 failed holiday requests terminal.
2. Back up and hash the currently installed files in owner-only private runtime
   directories. Retain the tested source revision/build provenance with backups.
3. Install these Ubuntu runtime modules from the tested revision:
   `apple_pim_fields.py`, `apple_pim_schema.py`, `apple_write_mcp.py`.
4. Install `apple_pim_fields.py` in the Mac's existing receiver package. No helper
   identity, credential, account, TCC setting, or receipt journal changes.
5. Build on the Mac in a separate staging directory. Back up then atomically
   replace `native-pim/calendar-cli` and `native-pim/reminder-cli` (the shared
   Swift binary). The unchanged `eventkit-helper`/`reminderkit-helper` do not need
   replacement. Do not install test binaries or use a live smoke-test script.
6. Restart the existing Calendar/Reminders tunnel services; resume the worker
   timer only after inspecting pending jobs and module compatibility. Read-only
   verification: source hashes, worker health, tool schemas/capabilities,
   destination inventory and exact authorized event inspection/fresh revisions.
   Refresh the ChatGPT connections and verify fresh-chat discovery separately.
7. Roll back by pausing the worker again, restoring the backed-up source modules
   and both Swift executables, restarting the two tunnels, and rechecking health.
   Do not reset receipts, recycle request keys, or auto-replay failed/uncertain
   jobs. Reinspect events after any version change because revisions may differ.

No additional sensitive permission is needed for the source/build tests already
performed. Deployment is pending authorization. A separate persistence test
would require explicit authorization for disposable Calendar records and their
cleanup (including recurring deleted/edited exceptions), using the existing
approved helper and no invitations. Until that succeeds, holiday reconciliation
and the actual school End Repeat edits remain pending.
