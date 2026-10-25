# Explicit headless collectors

Collectors remain on their legacy implementation until private configuration
selects an adapter. Call `configure_headless(config)` once before collecting;
calling it with `{}` resets every adapter to legacy. Selection never grants an
OS permission or authorizes another account or mailbox.

## Contacts

Build `src/personal_context/contacts_native.m` on macOS:

```sh
clang -fobjc-arc -framework Foundation -framework Contacts -framework AddressBook contacts_native.m -o contacts-native
```

Install/sign the executable at a stable private path. Separately grant Contacts
access to its responsible application/process. The helper checks full access,
rejects limited/denied/not-determined status without requesting permission, and
never launches Contacts. A fresh permission denial is an error, never an empty
snapshot or automatic GUI fallback.

```json
{"headless":{"contacts":{"mode":"native","helper":"/private/example/contacts-native","note_databases":["/absolute/private/example-library/Application Support/AddressBook/AddressBook-v22.abcddb","/absolute/private/example-library/Application Support/AddressBook/Sources/EXAMPLE/AddressBook-v22.abcddb"]}}}
```

AddressBook.framework is deprecated but preserves the exact legacy ABPerson and
ABMultiValue identities on the verified macOS release. Current native framework
note reads can silently omit notes. Therefore the Python adapter requires an
explicit list of readable Contacts source databases. It makes private consistent
SQLite backups and joins `ZUNIQUEID` to the native ID and `ZNOTE` to `ZABCDNOTE`.
All native IDs must have a replica row; missing relationships, unsupported schema
or conflicting duplicate notes abort the snapshot. No original database is opened
for writing. This preserves note text instead of accepting a lossy native result.
Freshness describes the local replica, not proof that iCloud/Exchange synchronized.

## Notes

```json
{"headless":{"notes":{"mode":"database","database":"/absolute/private/example-library/Group Containers/group.com.apple.notes/NoteStore.sqlite","legacy_database":"/absolute/private/example-library/Containers/com.apple.Notes/Data/Library/Notes/NotesV7.storedata"}}}
```

Each store is copied using SQLite's online backup API from a read-only connection,
including committed WAL. Temporary directories/files are owner-only and removed
after collection. The frozen copy uses immutable read-only access. The original
store's journal mode, WAL, data and attachments are never modified. Snapshots are
individually consistent; there is no cross-store atomic transaction.

The CloudKit store uses CoreData store UUID, entity and primary key for the exact
legacy IDs. It decodes bounded gzip/zlib protobuf `document.note.note_text` using
the [upstream schema](https://github.com/threeplanetssoftware/apple_cloud_notes_parser/blob/master/proto/notestore.proto).
Unsupported schemas or body encodings fail the snapshot. Locked/unavailable
bodies remain explicitly unavailable. Unmaterialized initial-fetch placeholders
with no title/folder are excluded, matching Notes.app visibility. Deleted notes
and Recently Deleted are excluded as in the existing collector.

When NotesV7 exists, explicit legacy-store configuration is required to preserve
older/Exchange account coverage. Legacy HTML is converted with native `textutil`;
that can change paragraph whitespace and nonbreaking-space representation.
Original HTML remains in `payload.bodyHtml`, alongside `bodyFormat` identifying
the conversion, so meaningful source formatting is retained. No `strip()` or
whitespace folding is applied to archived text. Cloud text is preserved exactly.
Database collection does not launch Notes, initiate sync or decrypt locked notes;
`replica_freshness` is `unknown`.

## Mail

`headless.mail.mode="local"` selects the existing SQLite/local message reader
without app launch or a fetch request. CLI/coordinator report local-replica-only
with unknown upstream freshness. A successful local scan proves no provider fetch.

Direct IMAP requires fresh, explicitly supplied provider authorization. Credentials
are never obtained from Apple Mail, Keychain, account databases or browser tokens.
Use an existing provider app password or OAuth access token authorized for the
intended account. Microsoft commonly requires OAuth; OAuth consent/refresh setup
is separate and token renewal is not performed by this adapter.

```json
{
  "mailbox_urls":["fiction://selected-inbox","fiction://selected-sent"],
  "headless":{"mail":{
    "mode":"imap",
    "identity_migration_acknowledged":true,
    "profiles":[{
      "host":"imap.example.invalid",
      "credentials_file":"/private/example/mail-credential.json",
      "mailboxes":[
        {"name":"INBOX","archive_mailbox_url":"fiction://selected-inbox"},
        {"name":"Sent","archive_mailbox_url":"fiction://selected-sent"}
      ]
    }]
  }}
}
```

The private credential JSON contains `username` and exactly one nonempty
`password` or `access_token`. It must be an owner-owned regular file with no group
or other permissions; symlinks are refused. A single profile can also be placed
directly under `headless.mail`. Profiles must cover every selected mailbox URL
exactly once; `all_mailboxes` never expands IMAP selection. Mailbox names must be
ASCII protocol names (providers using modified UTF-7 must supply the encoded
name explicitly).

Connections require verified TLS. Mailboxes are opened with `EXAMINE` (`readonly`),
and message bodies use `BODY.PEEK[]`; no flag updates, mailbox creation, message
movement, sending, CLOSE or expunge are issued. Recent mode scans three server
days. Missing UIDVALIDITY, truncated inventories and UID mismatches fail honestly.
Provider error response text is never included in public errors.

Provider UID identity differs from Apple's local mailbox row IDs. Until a verified
identity alias migration exists, records use `source=provider-imap` and always
`complete=false`, keeping legacy records and avoiding tombstones. Explicit
`identity_migration_acknowledged=true` acknowledges coexistence and possible
search duplicates; configuration is otherwise rejected before any network use.
Do not automatically enable direct Mail for a deployed archive just because the
adapter exists. Verify selected-account authorization and plan identity migration.

## Verification before enabling an adapter

Use fictional fixtures for public regression tests. Keep real device counts,
record identifiers and comparison artifacts in private operator storage. Compare
canonical field hashes and stable source IDs against the existing archive before
replacing an adapter. Verify Notes text, original HTML, dates and availability
separately; unsupported schemas and unmaterialized placeholders must remain
explicit. Record initial and final application state privately. Native permissions
and provider credentials still require verification on the operator's devices.
Fixture success alone does not establish live native or provider parity.
