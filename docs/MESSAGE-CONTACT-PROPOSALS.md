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

V1 recognizes only whole-message English statements in these forms:

- `My birthday is February 29.` or `My birthday is June 4, 1992.`
- `My home address is 123 Maple Street.`
- `My work address is 456 Oak Avenue, Example City, CA 90000.`

Birthday month names must be explicit. Optional years are preserved only when
stated; an absent year remains absent. Yearless leap days are valid. Invalid or
future birth dates, numeric/relative dates, age claims and appointment dates are
not extracted. Address support is intentionally narrow: numbered streets with
recognized English suffixes, optional Apt/Unit, and optional US-style city/state
and ZIP. It stores the stated address string and explicit Home/Work label; it does
not infer missing components, geocode, or assert deliverability.

Only available incoming iMessage/SMS text from a direct chat is considered. The
source must explicitly identify direction, system/spam flags and chat membership.
Outgoing messages, groups, replies, attachments, reactions, retractions, unknown
services and unsupported text abstain. Source is `payload.text`, never flattened
search text, summaries or attachment names. Whole-message matching rejects obvious
quotes, forwarding/context prefixes, hypothetical/temporary suffixes and embedded
instructions. It cannot prove that a seemingly literal statement is sincere or
was not an unmarked copy; these are suggestions only, with no calibrated confidence
claim. Unsupported language/formats abstain rather than guess.

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

List/show revalidate source and contact/identifier snapshots. Edited/deleted source,
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
and preservation of the source archive. Native Contacts behavior is not tested by
these tests.
