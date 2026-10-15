# Native Apple Calendar and Reminders Queued Writes Implementation Plan

> **For agentic workers:** Native inline execution. Follow the spec and work task by task. Steps use checkbox (`- [x]`) syntax.

**Goal:** Add chat-approved Calendar and Reminders creation through durable Ubuntu jobs delivered by SSH to the user's Mac and written into existing Apple accounts/lists through EventKit.

**Architecture:** The Ubuntu MCP queues exact approved payloads in an encrypted SQLCipher outbox. A systemd worker retries SSH delivery to a fixed Mac receiver, which validates and executes the existing EventKit-backed Apple PIM CLIs with broad EventKit access and the user's existing default or explicitly selected destination. Job states distinguish queued, completed, cancelled, failed, and ambiguous outcomes.

**Tech Stack:** Python 3.11+, existing SQLCipher, strict OpenSSH, systemd service/timer on Ubuntu, and the pinned Apple PIM Swift CLIs on macOS.

**Spec:** `docs/superpowers/specs/2026-10-15-apple-native-mac-queued-writes.md`

## Global Constraints

- Approval is required for each exact event/reminder before it enters the queue.
- Use existing Apple accounts and lists; never create a separate CalDAV account, calendar, or reminder list.
- Mac target is fixed by private configuration; SSH uses `BatchMode=yes` and `StrictHostKeyChecking=yes`.
- Queue data is encrypted with the existing SQLCipher runtime key and stored outside the source checkout.
- Payloads travel on SSH stdin to a fixed receiver command; model-provided fields never become shell commands or SSH command arguments. Native CLI arguments are passed as literal argv values.
- Mac-unreachable jobs remain queued; ambiguous post-send failures become `needs_review` and are never auto-retried.
- MCP `queued` means Ubuntu accepted the job; only a verified Mac receipt means `completed`.
- Do not claim an alert fired on time if the Mac was offline past the reminder due time.

## Review Focus

- Mac disconnects after receiving a job but before the SSH reply: avoid duplicate creation and expose `needs_review`.
- Duplicate request key with changed content: return a conflict and preserve the original job.
- Mac is offline across the due time: preserve the approved absolute due time and report late delivery.
- EventKit permissions or Apple PIM configuration block the destination: return a safe terminal error without leaking payloads.
- Existing default/explicit calendar or reminder list is absent or ambiguous: fail rather than silently create/select a new container.

---

### Task 1: Add encrypted Ubuntu write queue

**Files:**
- Create: `src/personal_context/apple_write_queue.py`
- Create: `tests/test_apple_write_queue.py`

**Interfaces:**
- `queue_job(kind, request_key, payload, db_path=None, key_file=None, now=None) -> dict`
- `job_status(job_id, db_path=None, key_file=None) -> dict`
- `pending_jobs(db_path=None, key_file=None, limit=50) -> dict`
- `cancel_job(job_id, db_path=None, key_file=None, now=None) -> dict`
- `claim_jobs(db_path=None, key_file=None, now=None, limit=10) -> list[dict]`
- `finish_job(job_id, state, error_code=None, db_path=None, key_file=None, now=None) -> dict`

- [x] Add SQLCipher table with unique job ID and request key, canonical payload hash, kind, encoded structured payload, timestamps, state, and sanitized error code. Follow `mail_send.py` private-directory/key/file-mode patterns.
- [x] Validate event/reminder fields, ISO-8601 timezone offsets, event end-after-start, title/notes bounds, and alert-offset bounds.
- [x] Make identical request-key retries return the existing job; changed content returns a conflict.
- [x] Implement atomic queued-to-delivering claim, cancellation only from `queued`, and terminal states without returning stored notes in status lists.
- [x] Add named tests `test_queue_requires_private_key`, `test_queue_rejects_naive_datetime`, `test_same_request_key_same_payload_returns_existing_job`, `test_same_request_key_changed_payload_conflicts`, `test_cancel_after_claim_fails`, and `test_status_omits_notes`.
- [x] Run `.venv/bin/python -m unittest discover -s tests -p 'test_apple_write_queue.py'`; expect all queue tests to pass.

### Task 2: Implement fixed Mac receiver and idempotency receipts

**Files:**
- Create: `src/personal_context/mac_pim_executor.py`
- Modify: `docs/SETUP.md`
- Modify: `examples/apple.example.json` or a dedicated `examples/mac-pim-executor.example.json`

**Interfaces:**
- `apply_job(payload, *, receipt_db_path=None, runner=None) -> dict`
- CLI: `python -m personal_context.mac_pim_executor --apply-stdin`
- Input: one bounded JSON object containing `job_id`, `kind`, and validated event/reminder fields.
- Output: one bounded JSON receipt with `job_id`, `state`, and a safe item identifier/result.

- [x] Read bounded JSON only from stdin; validate exact keys, job ID, timestamps, and payload shape again on Mac.
- [x] Use a private local receipt journal to return the same result for a completed job ID and detect an interrupted `applying` job. An interrupted write becomes `needs_review`, not an automatic duplicate attempt.
- [x] Invoke fixed `calendar-cli create` or `reminder-cli create` using argv arrays, exact ISO-8601 fields, and existing default or explicit existing destination. Keep the pinned Apple PIM configuration in `all` mode for calendars and reminders; never create containers.
- [x] Use pinned `reminder-cli create --due` with its default due-time alert for a reminder that fires at its due time. When an approved `alarm_minutes_before > 0` is requested, pass `--alarm N` and surface the Apple PIM warning that Reminders displays/fires at the earlier alarm time, not as a second alert while preserving the later due time.
- [x] Document Mac setup: install pinned Apple PIM CLI, run local authorization once, grant Calendar and Reminders access, configure broad EventKit access and existing defaults, install a fixed SSH-invoked receiver command, and keep SSH access limited to that command where practical.
- [x] Add named tests `test_executor_rejects_oversized_or_malformed_stdin`, `test_executor_passes_metacharacters_as_literal_argv_values`, `test_completed_receipt_replay_does_not_create_again`, `test_interrupted_apply_returns_needs_review`, and `test_cli_failure_is_sanitized`.
- [x] Run the focused Mac executor unit suite on macOS with mocked CLI runner; expect all tests to pass without accessing personal Calendar/Reminders data.

### Task 3: Add Ubuntu SSH dispatch worker

**Files:**
- Create: `src/personal_context/apple_write_worker.py`
- Create: `examples/personal-context-apple-write-worker.service.example`
- Create: `examples/personal-context-apple-write-worker.timer.example`
- Modify: `pyproject.toml`

**Interfaces:**
- `process_queued(*, target=None, remote_command=None, queue_options=None, ssh_runner=None) -> list[dict]`
- Read fixed configuration `PERSONAL_CONTEXT_APPLE_WRITE_TARGET`, `PERSONAL_CONTEXT_APPLE_WRITE_REMOTE_COMMAND`, and queue DB/key settings.

- [x] Preflight the Mac using a fixed remote health command before claiming work. Select only atomically claimed jobs, serialize JSON to SSH stdin, and use a fixed command with batch mode, strict host checking, short connect timeout, and bounded execution timeout.
- [x] If the health preflight fails, leave jobs queued. Once payload delivery begins, any missing/invalid receipt is ambiguous: mark `needs_review` and never retry automatically.
- [x] Accept `completed` only for a valid matching Mac receipt; sanitize all error paths and never log full job payloads.
- [x] Add a persistent systemd timer with a short bounded poll interval; create private service environment/config outside the checkout and prevent concurrent workers.
- [x] Add named tests `test_offline_preflight_keeps_job_queued`, `test_worker_sends_json_only_on_stdin`, `test_invalid_receipt_marks_needs_review`, `test_post_send_timeout_is_not_retried`, and `test_only_one_worker_claims_a_job`.
- [x] Run `.venv/bin/python -m unittest discover -s tests -p 'test_apple_write_worker.py'`; expect all worker tests to pass.

### Task 4: Expose MCP create/status/cancel tools

**Files:**
- Modify: `src/personal_context/source_mcp_server.py`
- Modify: `examples/mcp.example.json`
- Modify: `README.md`

**Interfaces:**
- Calendar source, when `PERSONAL_CONTEXT_APPLE_WRITE_ENABLED=1`: `queue_apple_calendar_event(request_key, title, start_at, end_at, notes="", alarm_minutes_before=None, calendar="")`.
- Reminder source, when enabled: `queue_apple_reminder(request_key, title, due_at="", notes="", alarm_minutes_before=0, list_name="")`.
- Add `apple_write_job_status(job_id)`, `pending_apple_write_jobs()`, and `cancel_apple_write_job(job_id)` to Calendar and Reminder MCP surfaces only when queue config validates.

- [x] Ensure tool descriptions demand prior approval of exact title, destination, local date/time/zone, notes, and alert, and say queued is not yet a native write. For a pre-due Reminders alarm, explain that Reminders will display/fire at the earlier alarm time, not preserve a second later due time.
- [x] Register mutation annotations accurately; absent/invalid config leaves mutation tools unregistered while read-only tools remain available.
- [x] Return only job ID/state/created timestamp from queue calls; status and pending outputs omit notes and other sensitive payload fields.
- [x] Document disabled-by-default setup and Mac-off queue behavior; keep examples fictional and with write flag off.
- [x] Add named tests `test_write_tools_absent_when_disabled`, `test_invalid_queue_config_keeps_read_tools_available`, `test_calendar_and_reminder_schemas_are_separate`, and `test_queue_status_cancel_tools_report_job_states`.
- [x] Run the focused source MCP registration suite; expect enabled and disabled configurations to expose exactly the documented tool set.

### Task 5: Configure private Ubuntu and Mac deployment

**Files:**
- Private only: Ubuntu SQLCipher queue DB/key, worker environment and systemd units, SSH target/known-host data; Mac Apple PIM configuration and local receipt journal.

- [x] Confirm existing Mac SSH target and host key are pinned; do not weaken `StrictHostKeyChecking` or publish a listener.
- [x] Install the Mac receiver/Apple PIM CLIs, authorize Calendar and Reminders interactively while logged into the intended macOS account, and confirm existing default calendar/list.
- [x] Install the Ubuntu timer and enable `PERSONAL_CONTEXT_APPLE_WRITE_ENABLED=1` only after transport and Mac authorization succeed.
- [x] Verify synthetic event/reminder jobs from Ubuntu appear in the existing native destinations, status transitions to completed, and no separate calendar/list is created.
- [x] Exercise an unavailable preflight and confirm a newly queued job remains queued, then reconnect and confirm delivery once. Exercise cancellation and ambiguous-timeout handling with synthetic jobs. A controlled failed SSH preflight was used; the Mac was not physically powered off.
- [x] Record observed retry/delivery behavior in private project status; do not claim phone alert timing beyond an item being created and syncing through the user's existing Apple account.

## Execution Notes

- User has explicitly selected queued Ubuntu-to-Mac delivery and native existing Calendar/Reminders destinations.
- Mac must be awake, Tailnet reachable, and the intended user logged in with the Apple PIM CLI already authorized by macOS TCC. Jobs can wait indefinitely while it is unavailable.
- The pinned Apple PIM revision already has `calendar-cli create` and `reminder-cli create`. `calendar-cli create --alarm N` alerts before event start. A timed Reminder defaults to an alert at its due time; `reminder-cli create --alarm N` shifts the time Reminders displays to that earlier alarm. Verify these user-visible behaviors on the Mac before runtime enablement.


## Implemented and verified — 2026-10-15

- Encrypted outbox, fixed SSH worker, native receiver receipt journal, opt-in
  Calendar/Reminders tools, setup docs and example systemd units implemented.
- Final full suite: 159 tests run, one unrelated Mac-only test skipped on Ubuntu.
  Mac receiver suite: 13 mocked tests passed on macOS.
- Private deployment installed and enabled: minute timer active, Calendar and
  Reminders MCP processes expose the queue/status/pending/cancel tools alongside
  existing reads. Existing refresh and Mail behavior preserved in private app.
- Existing Apple PIM Helper already has native permissions. Receiver launches it
  via Launch Services; direct SSH CLI permissions differ. Native successful JSON
  is authoritative when open -W loses a wait race after the app exits.
- Synthetic event/reminder creates reached existing system defaults, read back
  exact title/notes/timing and native reminder due alarm, and were removed.
  Controlled offline preflight, real reconnect delivery, native receipt replay,
  identical request retry and queued cancellation verified. Post-send ambiguity
  and crash behavior verified by tests. No physical Mac shutdown or phone
  notification delivery/timing claim is made.
- Ruling: Configured default keys are snake_case; explicit/configured names must
  resolve uniquely. For an unspecified destination, leave the CLI target flag
  unset so EventKit uses the actual system default even when names repeat across
  accounts. No container creation or account changes.
- Ruling: Pinned Reminders writes minute-level local components. Reject nonzero
  seconds and repeated local DST hours rather than silently changing approved
  times. This is a native Reminders alert, not an Apple Clock countdown timer.
- Fresh review identified configured-default parsing, optional corrupt-queue
  startup, and repeated DST-hour issues. All were fixed with failing regression
  tests followed by passing focused/full runs.
- Chat clients can retain the old tool catalog until their next reconnect or
  connector refresh; the live MCP servers now advertise the new tools.
