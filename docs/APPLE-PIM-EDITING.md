# Structured Apple Calendar and Reminders writes

The MCP surfaces expose direct typed changes to real native items. There is no
separate editor or web application. Ubuntu holds encrypted queued writes; the
already-authorized Apple PIM Helper app applies them on the Mac. Existing native
accounts, calendars and lists are used.

## Workflow

1. Find an archived item using the existing read tools.
2. List native destinations when selecting or changing a calendar/list. IDs are
   preferable to names, especially when accounts contain duplicate names.
3. Inspect the live native item. Calendar inspection needs the native event ID
   from `payload.id` and the original occurrence start, not the archive's
   composite `id|timestamp` record ID. Reminders use their native item ID.
4. Submit the authorized patch or deletion with the returned `revision` and a
   new request key. Calendar changes require explicit `scope`: `this` occurrence
   or `future` occurrences. Titles are never deletion selectors.
5. `queued` confirms acceptance on Ubuntu. Only a completed write job confirms
   the native operation. Reinspect the live item after completion. The encrypted
   read archive catches up through its ordinary collection schedule.

Reusing the request key for identical retries returns the existing job. A
changed request using that key fails. Automatic route calculations use the
original logical request for this comparison; changing traffic estimates do not
create duplicate jobs. A stale native revision fails before saving. Uncertain
delivery or readback is `needs_review`, with no automatic replay.

An offline Mac delays writes even though Ubuntu and the MCP remain available.
Native state readback does not prove phone synchronization or notification
delivery. Cancellation of an outbox job never deletes an existing Apple item.

## Calendar

Tools: `queue_apple_calendar_event`, `inspect_native_apple_calendar_event`,
`update_apple_calendar_event`, `delete_apple_calendar_event`,
`list_apple_calendars`, `set_apple_calendar_driving_time`,
`edit_apple_calendar_attendees`, `edit_apple_calendar_attachments`,
`apple_pim_capabilities`, and the existing write-job tools.

The creation tool's `details` object and the update tool's `changes` object
expose location, notes, URL, timezone, all-day state, alerts, recurrence and
availability. Start/end are absolute offset ISO timestamps. All-day boundaries
must be local midnight; the end date is exclusive. On creation, title, start,
end, notes and destination remain top-level arguments for compatibility.

Example partial change, using values obtained by native inspection:

```json
{
  "request_key": "fictional-meeting-location-1",
  "item_id": "native-id-from-inspection",
  "occurrence_start_at": "2031-11-02T12:00:00-05:00",
  "expected_revision": "64-hex-character-revision-from-inspection",
  "scope": "this",
  "changes": {"location": "1 Apple Park Way, Cupertino, CA 95014", "notes": ""}
}
```

Absent fields are preserved. Empty text clears notes/location/URL. `alerts` is
an array of up to five distinct minute offsets before start; `[]` clears timed
alerts. `recurrence: null` removes repetition; otherwise supply frequency,
optional interval, and either count or an offset ISO `until`.

### Automatic car travel

Timed event creation with a physical location, and location/start edits,
automatically calculate car travel through Apple Maps. `automatic_driving=false`
is an explicit opt-out. Virtual locations and all-day creation are excluded.
The dedicated driving tool recalculates an existing event without changing its
other fields.

The origin comes from the encrypted phone travel archive, never Ubuntu's or the
Mac's location. The latest observation must be at most five minutes old, at
most 250 meters uncertain, and not more than 30 seconds into the future. A
missing/stale location or ambiguous geocoded place stops the operation. No
credentials or coordinates are added to job-status receipts or source files.

The adapter writes and verifies Calendar's real travel duration and structured
destination. Setting the duration uses a guarded private EventKit accessor.
The estimate expires after five minutes before saving. It is a save-time
estimate; continuous recalculation and Apple's time-to-leave notification
configuration are not implemented. Phone location sharing must stay active.

The [automatic updater design](superpowers/specs/2026-10-16-automatic-travel-updater-design.md)
describes a proposed bounded background policy. It is not implemented or enabled.

### Native attendees and attachments

Attendee changes add/remove exact email addresses, preserving the remaining
roster. They require `allow_invitation_delivery=true`: native saves may send real
invitations or cancellations. Obtain explicit recipient and delivery approval
first. Organizer/self removal and non-organizer edits are rejected. The guarded
EventKit factory is informed by [go-eventkit](https://github.com/BRO3886/go-eventkit)
revision `a3dbabc9ea2b41f2725437ea1e58c6c53b835702`; its MIT attribution is included.
Unsaved attendee add/remove has been tested; real invitation delivery has not.

Calendar supports native PNG, JPEG and PDF file attachments. Inspection returns
stable attachment IDs, filenames, type, availability, size and SHA-256, not file
paths. Removal requires exact inspected IDs. Attached bytes are saved through
EventKit, read using its security-scoped URL wrapper, and verified again after
the private staging files are removed. No public upload, database edits or
broader disk-access permission is involved. Attachment edits on invited events
also require invitation-delivery consent because a provider may send updates.
Apple's [Calendar file attachment guide](https://support.apple.com/guide/calendar/icl58679aba2/mac)
describes the corresponding native app feature. PNG/PDF persistence and removal
were verified on disposable non-recurring iCloud events; recurring attachment
edits and cross-device sync have not been established by those checks.

The bounded transport accepts `filename`, `media_type`, `content_base64` and
`sha256`; no caller-selected local paths or fetch URLs. Limits are 2 MiB per
file, 4 MiB per batch and five files. Bytes stay in the encrypted outbox and
private native temporary files; receipts never include them. Native validation
decodes images with pixel limits and requires a readable, unencrypted PDF.
Missing cloud bytes are reported unavailable rather than silently downloaded
from an arbitrary URL. Native readback does not establish cross-device sync.

## Reminders

Tools: `queue_apple_reminder`, `inspect_native_apple_reminder`,
`update_apple_reminder`, `delete_apple_reminder`, `list_apple_reminder_lists`,
`set_apple_reminder_urgent`, `add_apple_reminder_subtasks`,
`edit_apple_reminder_tags`, `edit_apple_reminder_attachments`,
`apple_pim_capabilities`, and write-job tools.

Updates expose title, notes, URL, due time, timezone, list, priority, completion,
timed alerts, recurrence and geofence alarms. `completed=true/false` completes
or reopens an item. Completing a repeating reminder may advance its next due
date, following Apple's behavior. `due_at: ""` removes its due time and timed
alarms. Seconds must be zero; ambiguous repeated local DST hours are rejected.

Alerts are minute offsets before due. Apple's earlier-alarm display behavior
can make the reminder appear due at that earlier time; explain it before
approval. Native readback and job receipts preserve this warning. A priority
of 1 is high priority and is never represented as the native Urgent switch.

### Native Urgent and subtasks

The adapter uses a narrow ReminderKit interface based on
[RemCTL](https://github.com/viticci/remctl) reference revision
`d3985293a01aa1c2da761ff442812a148be9964f`. Attribution and its MIT license are
included in `third_party/remctl`. This writes through Apple's native save
request, never through direct database edits. It requires no new calendar/list
or separate account.

Inspect `private_metadata.supports_urgent` and `supports_subtasks` for the
selected item. Exchange lists do not support these features; an existing
iCloud list is required. Unsupported accessors/accounts fail explicitly.
Private APIs can change with macOS updates; native readback must verify each
save before completion is reported.

Enabling Urgent requires an existing exact due date and time. Device alarms
still depend on Apple's device settings and location-device choice; native
state alone is not proof that an alarm rings. Subtask creation accepts up to
50 title/optional-notes objects in one native save. Inspect the parent after
completion to obtain child IDs. The ordinary reminder inspect/update/delete
tools operate on those children, including completion and reopening.

Deleting a parent with children is rejected before saving. Explicitly approve
and delete the child IDs first, then reinspect/delete the parent. This prevents
an unmentioned cascade.

### Native tags and image attachments

Tags use the synced native hashtag context, not title or notes text. Supply
`changes.set_tags` to replace (including `[]` to clear), or `add_tags` and/or
`remove_tags` to preserve unrelated tags. Names omit `#`; duplicates and
contradictory changes are rejected. Inspect `private_metadata.supports_tags`.

Image attachments use ReminderKit's native image save context and exact native
IDs for removal, with the same bounded encrypted transport and byte verification
as Calendar. PNG and JPEG are supported. PDF/generic-file attachment writes are
deliberately rejected: a private file-add selector exists, but that alone does
not prove Reminders renders or syncs those files. RemCTL likewise limits its
native attachment path to images. A private stable document URL in the reminder's
URL field remains an explicit alternative when the document already has an
authorized hosting location; this adapter does not upload or convert PDFs.

## Native installation

Keep the existing authorized Apple PIM Helper and upstream CLIs. Build these
additional adapters into a separate private directory on the Mac:

```sh
sh scripts/build_apple_pim_native.sh
```

In the Mac receiver's private launcher, set:

```sh
export PERSONAL_CONTEXT_APPLE_NATIVE_BIN_DIR="$HOME/.local/share/personal-context-bridge/native-pim"
```

Install the updated bridge Python modules for that receiver. The launcher uses
Launch Services `open --env APPLE_PIM_BIN_DIR=...` to select these adapters only
for structured operations. It does not modify the authorized helper app or
replace existing collector binaries. The helper's app identity remains intact.

For automatic driving, set `IPHONE_TRAVEL_DB` and `IPHONE_ARCHIVE_KEY_FILE` in
the Calendar MCP's private environment to its existing encrypted phone archive
and unlocked key. No phone or map service credentials go in source control.

Restart the Calendar/Reminders MCP servers after deployment. Refresh each
connector's catalog if the client still shows the previous tool list.

Mac integration verification (creates/removes fictional items in existing
destinations, including an iCloud list; uses public test coordinates):

```sh
python scripts/check_apple_pim_native.py
python scripts/check_apple_pim_extensions.py
```

## Remaining feature gaps

This adapter does not claim complete Apple-app parity. Reminders PDF/generic-file
attachments, sections/shared assignment, calendar/list creation and sharing,
and continuous time-to-leave updates are not implemented. The
typed tools reject unsupported properties rather than approximating them with
notes or unrelated items. RemCTL provides a native-framework path for several
additional fields; each needs its own bounded validation/readback
contract before being exposed here.
