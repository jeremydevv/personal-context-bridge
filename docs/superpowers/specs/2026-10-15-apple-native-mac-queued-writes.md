# Native Apple Calendar and Reminders writes through a queued Mac executor

Date: 2026-10-15
Status: User-directed design

## Goal

Let chat-approved jobs create events and timed reminders in the user's existing
Apple Calendar and Reminders accounts/lists. Do not add or require a separate
calendar account or list. Queue jobs durably on the archive server and deliver them to
the Mac when it is reachable.

## User flow

1. Chat uses context to prepare one exact event or reminder with a resolved
   operator-configured timezone and date/time and any requested alert.
2. The user approves that exact item before the MCP queues it.
3. Ubuntu stores the job in a private encrypted outbox and immediately returns
   its job ID and `queued` state. Queued means the Mac has not created the item.
4. A persistent Ubuntu worker attempts delivery over strict-host-key SSH to a
   fixed Mac target. When the Mac is unavailable, the job stays queued and the
   worker retries later.
5. A fixed Mac receiver validates the payload and invokes the existing pinned
   Apple PIM Calendar or Reminders CLI through EventKit. It uses the user's
   existing EventKit calendars and lists. With no explicit destination, use the
   configured existing default; never create a calendar or reminder list.
6. The user can ask for job status or cancel a job that has not begun delivery.
   The MCP reports `completed` only after the Mac receiver confirms the native
   write; it reports ambiguous writes as `needs_review` instead of retrying and
   risking a duplicate.

## Access and destination

- Grant the Mac's Apple PIM processes broad Calendar and Reminders access and
  configure those domains in `all` mode. Do not restrict the writer to one
  hard-coded calendar or reminder list.
- Default destinations remain the user's existing Apple PIM defaults. Permit an
  explicit existing calendar/list name or identifier when requested. Reject
  missing, read-only, or ambiguous destinations rather than creating containers.
- No Apple Account password, CalDAV credential, or separate CalDAV account is
  used. Ubuntu-to-Mac SSH remains private, key-authenticated, and strict about
  the pinned host key.
- Queue tools create only. Edit, delete, completion, and container management
  remain out of scope for this first implementation even though EventKit access
  covers the broad existing store.

## Queue and delivery contract

- Store only approved structured fields: job ID, request key, kind, title,
  absolute timezone-aware date/time, notes, explicit alert offset, optional
  existing destination, timestamps, state, payload hash, and sanitized error
  code. Use the existing SQLCipher runtime key and private data directory.
- An identical request key and payload returns the existing job; reuse with
  different content returns a conflict. Mac receipt journal records completed
  job IDs and item identifiers, not payload text.
- State transitions are `queued -> delivering -> completed`, with terminal
  `cancelled`, `failed`, or `needs_review` outcomes. SSH failure before sending
  the payload leaves a job queued. A timeout/disconnect after the Mac may have
  received it is ambiguous and must never be automatically retried.
- Preserve the approved absolute due time if a reminder reaches the Mac late.
  Report late delivery clearly; do not silently move its due time or claim its
  alert fired on time.
- Send JSON on SSH stdin to a fixed remote command; never put item text in SSH
  command arguments or routine logs, and never construct a remote command from
  model-provided text.
- EventKit/Apple Reminders represents a timed reminder's due alert at the due
  moment by default. An earlier Reminders alarm shifts the time Reminders shows
  to the alarm time; it does not provide a second alert while preserving the
  separate later due time. Tool approval must state the displayed/fire time.
  Calendar event alarms can be set relative to event start.

## Mac availability and limits

- Mac being offline does not lose queued work; writes wait until it is awake,
  reachable over Tailnet, and its logged-in user's session and EventKit
  permissions are active.
- If the reminder due time passes while the Mac is unavailable, it can be
  created late with the original due time after reconnection; an on-time alert
  cannot be guaranteed.
- The Mac helper must be authorized interactively once under the intended
  macOS account. Do not attempt to bypass macOS TCC prompts over headless SSH.

## Rollout

- Keep write tools disabled until the Mac target, SSH host key, Apple PIM CLIs,
  Calendar/Reminders permissions, and Ubuntu worker schedule are confirmed.
- Verify synthetic job queueing on Ubuntu, delivery to the Mac, creation in an
  already-existing calendar/list, offline retries, duplicate request handling,
  cancellation, and ambiguous transport outcomes.
- User-side one-time work: keep the Mac logged into the account whose Calendar
  and Reminders should be changed; grant Calendar/Reminders permission when
  prompted. No iPhone account addition is needed; existing account sync remains
  Apple's responsibility.

## References

- Apple EventKit create/save and permission model:
  https://developer.apple.com/documentation/eventkit/creating-events-and-reminders
- Pinned Apple PIM Calendar CLI implementation and create options:
  https://github.com/omarshahine/apple-pim/blob/4e155fc5a393c11fab8853565211422d02562a0a/swift/Sources/CalendarCLI/CalendarCLI.swift
- Pinned Apple PIM Reminders CLI implementation and due/alarm semantics:
  https://github.com/omarshahine/apple-pim/blob/4e155fc5a393c11fab8853565211422d02562a0a/swift/Sources/ReminderCLI/ReminderCLI.swift
