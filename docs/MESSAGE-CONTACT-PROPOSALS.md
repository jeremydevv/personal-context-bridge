# Local Messages-to-Contacts proposals

This optional command discovers suggestions in an existing encrypted archive. It
never writes Contacts, queues Apple actions, requests Mac permissions, calls a
model/provider, or installs a timer. It is not registered as an MCP write tool.
`reviewable` means a human may inspect a suggestion, not that it is safe or approved
to apply. Every response has `write_eligible: false`.

## Run manually

Use a private, separate ledger and the existing private 32-byte archive key.
Install the `mcp` optional dependencies for SQLCipher. Do not copy live archives,
keys, proposals or command output into a public checkout, issue or test fixture.
Choose a bounded scope deliberately before evaluating real conversations.

```sh
python -m personal_context.contact_proposals \
  --archive "$ARCHIVE_PATH" --ledger "$PROPOSAL_LEDGER_PATH" --key-file "$ARCHIVE_KEY_PATH" \
  scan --start 2026-10-01T00:00:00Z --end 2026-10-04T00:00:00Z \
  --sender alice@example.test --limit 500
```

Dates above and the sender are fictional examples. Set the three path variables to
private local paths. The date range is start-inclusive/end-exclusive, requires
absolute offsets and may span at most 31 days. `--sender` can repeat and matches the
archived sender exactly; omitting it selects all senders in the date range. Scans
accept at most 1,000 messages (default 500). Exceeding the limit aborts the scan
without recording a partial result: narrow the scope and retry. No scan runs by
default when opening the ledger or installing the package.

With the same three global path options, use:

```text
list --limit 50 --offset 0
show PROPOSAL_ID
reject PROPOSAL_ID
```

`list` returns stable pagination and state; `show` includes evidence pointers,
message/source digests, exact extracted spans, timestamps and identity baseline.
Treat this output as private. `reject` records a durable rejection; rescanning the
same claim does not undo it. There is deliberately no approve/apply/write command.

## Extraction and attribution

The conversational v2 recognizer finds explicit sender-owned facts embedded in
ordinary English messages, including greetings, extra sentences, ordinal days,
month abbreviations and more than one field in a message. Examples:

- `Hey! My bday’s on June 4th 😊`
- `Oh, I was born on the 4th of June, 1992. How about you?`
- `My birthday is coming up on March 8.`
- `Sure, I live at 123 Maple Street. Come by sometime!`
- `I just moved to 123 Maple Street, Example City, CA 90000!`
- `My office is at 456 Oak Avenue, Example City, CA 90000.`
- `Here’s my address: 123 Maple Street` (label unknown, blocked for review).

Birthdays support month-first and day-first named dates, ordinal suffixes and
optional explicitly stated years. No year is inferred from age, message time,
summary text or archived birthday representations. Invalid/future birth dates and
ambiguous numeric/relative dates abstain. Address support remains limited to numbered
streets with recognized English suffixes, optional Apt/Unit/Suite and optional
US-style city/state/ZIP. Stated strings remain partial when incomplete; there is no
geocoding or verification of deliverability. Residence/work labels come from explicit
meaning (`I live at`, `my office`); generic `my address` has a null label and is
blocked rather than silently assigned Home.

Clear question-and-answer turns are supported: an outgoing `When’s your birthday?`
followed by the same direct correspondent’s `June 4th` can propose a birthday;
`Where do you live?` followed by an address can propose a residence. The question
must be the immediately previous archived turn in the same single stable direct
chat, within 24 hours, within the explicit scan scope. Multiple-topic questions,
intervening turns, unknown reply targets, grouped participants, missing stable chat
IDs and unresolved question forms abstain. A sender-only scan intentionally omits
outgoing questions, so it does not infer facts from those answer fragments.

Only available incoming iMessage/SMS text can produce proposals. Outgoing text can
supply question context but never becomes a proposal’s subject. System/spam messages,
retractions, reactions, attachments and unknown services are excluded. Text comes from
original `payload.text`, never summaries, flattened search bodies or attachment names.
Obvious quotes/forwarding, reported speech, negation, uncertainty, temporary stays,
future/hypothetical moves and instruction-like content conservatively block extraction.
Unsupported forms abstain rather than guess. This remains an explicit local rule
recognizer, not a general semantic model or a calibrated confidence score. Unmarked
copying, deceptive statements and sarcasm cannot be reliably proven absent; every
result remains a human-review suggestion with native identity unverified.

Sender resolution uses archived email/phone identifiers, never names or extracted
values. Missing/duplicate matches are blocked. Phone senders require an explicit
international `+` form; there is no country-code inference. Shared/recycled accounts
and numbers cannot be fully resolved from archive identifiers. Archive contact IDs
are not treated as native card/account IDs. Those remain null and unverified.

An existing archived birthday or any address creates a review conflict; values are
never overwritten. Different active birthday claims or addresses for the same label
are blocked as competing claims. Home and Work claims are independent. No automatic
newest-message-wins or freshness-is-truth policy is used; inspect evidence dates.

## Persistence and invalidation

The separate ledger requires SQLCipher, a private regular 32-byte key, and private
file permissions. It cannot alias the archive/key or be reused with another archive
path. There is no plaintext fallback. The archive is opened in read-only/query-only
mode and is not migrated. Ledger initialization does not change native sources or
existing Calendar/Reminders jobs.

Claims deduplicate by policy, archived subject, field and normalized value. Multiple
messages support one claim; repeated scans do not duplicate evidence. The encrypted
ledger stores the extracted value, source pointers/digests/spans, contact baseline,
scan bounds and local audit events, rather than whole conversations. Rejections
survive rescans. SQLite transactions serialize ledger writes and keep each bounded
scan atomic. This version has no network service and no scheduled worker.

List/show revalidate source and contact/identifier snapshots. Question-and-answer
evidence also stores and validates the exact question record/digest and checks for
new intervening turns in that chat. Edited/deleted source,
changed contact snapshot, new ambiguous matches or policy changes invalidate that
support; a claim becomes stale when it has no valid support. Unchanged supporting
messages can keep the same claim reviewable. Revalidation describes the local
archive, not live Apple Contacts. Scan again explicitly to discover new facts or
rebuild evidence after changes.

Values in stale/rejected claims remain encrypted locally for review/audit; this
version does not implement retention/secure deletion or an automatic cleanup job.
Choose retention before real-message evaluation. To discard a disposable evaluation,
close the process and remove the separate ledger and any SQLite sidecars according
to local storage policy; do not remove the source archive/key. Encrypted storage is
not a guarantee of secure erasure from backups or underlying disks.

## Boundary before native writes

A future writer needs separately approved implementation, live card/account mapping,
Contacts authorization, yearless birthday and labeled-entry fixture validation,
current native field readback, exact per-proposal approval, idempotent receipts,
uncertain-delivery handling and guarded field-only undo. This command implements
none of those capabilities. Archive linkage, a reviewable status, or a successful
synthetic test cannot authorize a real contact update.

Validation uses fictional encrypted archives and covers attribution, conflicts,
source invalidation, deduplication, rejection, pagination, scope overflow, CLI use,
conversational phrases, multiple fields, adjacent questions/answers, context invalidation,
and preservation of the source archive. Native Contacts behavior is not tested by
these tests.
