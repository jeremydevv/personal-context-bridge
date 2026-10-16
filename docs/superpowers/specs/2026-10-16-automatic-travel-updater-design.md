# Automatic Calendar Travel Updater

Status: proposed design for review, not implemented or enabled.
Date: 2026-10-16.

## Intent and boundaries

Keep a managed event's native Calendar travel duration current using automobile
ETA from the user's fresh phone location to the event's mapped destination.
Ubuntu schedules work; the existing authorized Mac adapter performs MapKit
routing and EventKit writes. No new calendar, CalDAV account, location service,
public upload, or user-facing editor is required.

The user approved writing this design and implementing the separate native
metadata extensions. This document does not authorize enabling an ongoing
background policy. Implementation planning follows review of this spec.

This is distinct from Apple's Time to Leave notification service. Updating the
travel-duration field does not prove that a phone will notify the user. The
updater must not create shadow reminders, change ordinary alerts, guess a home
address, or claim it controls Apple's notification delivery.

## Alternatives

1. Use only Apple's Time to Leave. This is the least custom code, but its likely
   origin is Apple's choice, not necessarily the latest archived phone fix, and
   it does not continuously update the saved travel block.
2. Recommended: bounded Ubuntu scheduler using the existing native adapter,
   encrypted outbox, fresh phone archive, and per-event conflict checks. This
   fits the current deployment and makes failures inspectable.
3. A new always-running Mac or iPhone application. This could integrate more
   closely with device location, but adds permissions, signing, lifecycle and
   distribution work. It is unnecessary for the first version.

## MCP contract

- `set_apple_calendar_travel_policy`: create/change an explicitly approved policy
  selecting exact event IDs/occurrences or an allowlist of existing calendar IDs.
  Include enabled state, arrival buffer (default 0, range 0-120 minutes), horizon
  (default 24 hours, maximum 48), and explicit exclusions.
- `inspect_apple_calendar_travel_policy`: return scope, enabled/paused state,
  next check, last native completion, stale-origin state, and safe error codes.
- `pause_apple_calendar_travel_policy` / `resume_apple_calendar_travel_policy`:
  durable controls, version-checked. Resume reconciles live state first.
- `delete_apple_calendar_travel_policy`: remove future management, not the event,
  its last saved travel duration, or unrelated user alerts.
- `preview_apple_calendar_travel_update`: one read-only fresh calculation with
  proposed ETA/departure; does not enable a policy or save an event.

Selecting a calendar is permission to manage only eligible upcoming events in
that calendar, not other calendars. No policy is created implicitly by an
ordinary event edit. Existing save-time automatic driving behavior is unchanged.

## Eligibility

Only writable, timed, not-cancelled events with one unambiguous physical mapped
destination are eligible. Skip all-day/virtual events, past starts, read-only
calendars, birthdays and unresolved destinations. First version excludes events
with attendees and shared calendars: background saves can otherwise send real
provider updates. Never silence provider notifications through undocumented
suppression flags. Report these exclusions in policy inspection.
Require a verified native shared-calendar capability check; unknown sharing
state is ineligible, not assumed private.

First version manages non-recurring events and explicitly selected recurring
occurrences only. A calendar-wide policy does not silently detach every future
occurrence of a recurring series. Each authorized recurring write uses `this`
scope and the original occurrence key; series-wide edits are not inferred.

## Scheduling and load

A dedicated supervised Ubuntu user timer wakes every minute. It selects due
policies, with a global nonblocking lock and per-event leases. Recalculate every
30 minutes for starts 6-24 hours away, every 5 minutes within 6 hours, and stop
at the event start. Policies may extend discovery to 48 hours, but routing starts
within the 24-hour active window. Cap each tick at ten route requests and one
in-flight write per event; defer remaining work fairly.

Only save when rounded travel duration changes by at least 60 seconds or a
managed destination/start/buffer changes. Route for arrival at event start minus
the buffer, and save rounded route ETA plus buffer as the managed native travel
duration. Keep ETA and buffer separate in encrypted state and preview output;
this makes departure equal start minus ETA minus buffer without changing the
event's start/end. Cache successful destination
geocoding by normalized place and structured coordinates, not ETA. Traffic ETA
is recalculated on schedule. Honor native rate limits with exponential backoff,
jitter and a maximum 30-minute delay; never retry in a tight loop.

## Data and delivery

Use separate policy/state tables in the existing SQLCipher outbox database with stable policy ID, generation,
scope, configuration, last/next check, per-occurrence state, last managed native
travel value, last native revision and pending outbox job ID. Runtime state and
keys stay outside source. Reuse the existing unlocked archive key and existing
encrypted write outbox, not a plaintext scheduler database.

For each candidate:

1. Check policy generation/enabled state and the event's live eligibility.
2. Read the latest encrypted phone location. Require age <=300 seconds, future
   skew <=30 seconds, uncertainty <=250 meters, finite valid coordinates.
3. Ask the authorized Mac for an Apple Maps automobile ETA to the event's exact
   destination, arriving at event start minus the approved buffer.
4. Inspect live again. If start/destination changed during routing, discard the
   estimate and replan next tick. If a human changed the last managed travel
   duration, pause this event with `manual_override`; do not overwrite it.
5. Queue a driving-only patch with exact native ID, original occurrence start,
   current revision and `this` scope. Preserve notes, alerts, attendees, dates,
   attachments and all other fields.
6. Recheck policy generation in the same database transaction that claims its
   managed job. Policy disable and queue invalidation use that transaction boundary.
   Cancel a still-queued obsolete job. Disabling cannot undo an already-started
   native save; surface that state rather than claiming instant cancellation.
7. Native application checks both origin and estimate freshness again. Only a
   verified native completion advances `last_applied` and managed travel value.

Request identity binds policy generation, occurrence identity, inspected revision
and scheduled computation slot. Identical delivery retries reuse that key. Do
not create a new key to replay an ambiguous write. A queue job holds the exact
route snapshot, not a mutable pointer to the latest location.

## Failure and restart behavior

- Stale/missing/inaccurate phone fix: leave the last saved duration unchanged,
  record `location_stale`, and retry on the next scheduled check. Never substitute
  Ubuntu/Mac location, previous-event address, or home/work.
- Offline Mac: leave work due, with bounded backoff. Do not accumulate one queued
  route per tick. An estimate older than five minutes cannot be applied later.
- Revision conflict: discard the estimate; re-read next tick. A new revision is
  not permission to overwrite a manual travel override.
- Uncertain save/readback (`needs_review`): suspend that event's policy work until
  explicit reconciliation against live state. No unattended replay.
- Deleted/moved/out-of-scope event: retire its work and cancel any unclaimed job.
  Do not recreate it or follow it into an unauthorized calendar.
- Process restart: recover leases; reconcile pending jobs first, then inspect
  live items. Never replay missed historical checks or extend expired routes.

## Privacy and observability

Origins, destinations, native item IDs and policy scope stay encrypted at rest.
Pass content through stdin/private temporary files, never shell interpolation
or process arguments. Do not log coordinates, titles, addresses, attachment
bytes, emails, or provider diagnostics. Return safe status codes and timestamps.
Prune transient route snapshots after terminal completion according to the
existing outbox rules; keep only minimal encrypted managed-state records.

The service is quiet by default. Policy inspection exposes stale inputs,
unsupported events and pending/uncertain writes. A future notification channel
needs separate user approval; this design does not add recurring chat messages.

## Verification and rollout

Unit tests use a virtual clock and fictional events to cover freshness bounds,
scheduling/fairness, cache limits, buffers, deduplication, policy generation,
pause/resume, manual overrides, deleted/moved events, conflict, offline Mac,
estimate expiry, rate limits, crash recovery and uncertain-save suspension.

Integration tests use the real encrypted outbox and bounded mocked routing, then
disposable native events with public test coordinates. Verify unrelated fields
and alerts survive. Run two concurrent ticks to prove one in-flight write.
Disable while queued and while delivering, checking the reported distinction.
No invitations or real personal appointments are changed by tests.

Rollout begins disabled. First run is preview-only on one explicitly selected
fictional event. Enable one user-selected real event only after scope approval
and a fresh phone fix; then review before any calendar-wide policy. Do not claim
phone synchronization or Time to Leave delivery from Mac readback alone.

## References

- [Apple: location and travel time](https://support.apple.com/en-kz/guide/calendar/icl43600/mac)
- [Apple: Calendar alert settings](https://support.apple.com/en-lamr/guide/calendar/icl40727/mac)
- Existing `apple_driving`, `apple_write_queue`, `apple_write_worker` and guarded
  EventKit native adapter in this repository.
