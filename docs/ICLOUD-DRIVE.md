# iCloud Drive

The main Personal Context MCP exposes eleven tools: status, folder segments,
filtered listing/search, AI metadata search, file info, text/chunk reads, native
tagging, folder creation and regular-file moves. Native Finder-tag checks are
mandatory for every data operation; the Mac receiver must be installed and enabled.
Configured protected files and tagged-folder descendants stay inaccessible.
Writer permission has no delete, content upload or overwrite operation.

The experimental Rclone authentication setup below remains an independent local
test path. Its listing verification does **not** verify the guarded MCP connection.
See the native receiver section for required connection/permission checks.

## Reading refresh status truthfully

The common `data_source_status` / `data_refresh` iCloud entry describes refresh
coordination, not native connection readiness. The legacy capability value
`requires_auth` is a classification, **not an observed failed authentication**;
`enabled` controls refresh configuration, not the native connection. Status adds
`capability_scope=refresh_coordination`, `native_authentication=not_checked` and
`native_access=not_checked` to make this distinction explicit, including when the
refresh ledger is unavailable.

Use `icloud_drive_status(probe=false)` for setup metadata. Its experimental Rclone
setup state is separate from `native_access_enabled`; neither establishes live
native access. `probe=true` additionally contacts the native receiver and performs
a bounded allowed listing. Do not perform that probe merely to read metadata.

The main MCP registers the eleven iCloud tool names independently of native
runtime enablement. Missing client-discovered names require checking the existing
server deployment/catalog and app discovery; they do not establish failed login,
and must not be remedied by automatically enabling access or adding credentials.

## Experimental Linux authentication

The community branch at https://github.com/thisiscamk/rclone/tree/iclouddrive-yubikey-testing
adds native libfido2 security-key support. It is not an upstream security-reviewed
release. Pin commit `c38ffc967293acb71a9cd11a04fa08068c77e0a7` and review it before
use. Source evidence: https://github.com/rclone/rclone/issues/9734 . Independent
Debian/Thetis results cover login, folder listings and roughly twelve hours of
saved-session reuse; they do not guarantee expiry behavior or session portability.

Build outside the checkout using Go >=1.26, a C compiler, pkg-config and libfido2
development headers/runtime. Keep the binary separate from any standard Rclone:

```sh
CGO_ENABLED=1 go build -tags libfido2 -o /private/runtime/rclone-fido2 .
RCLONE_CONFIG=/notfound go test -race -tags libfido2 ./backend/iclouddrive/api ./backend/iclouddrive
```

Set `PERSONAL_CONTEXT_ICLOUD_DIR` to a private directory containing that binary;
it defaults to `~/.local/share/personal-context-icloud`. Set
`PERSONAL_CONTEXT_KEY_FILE` to the existing unlocked 32-byte archive key. Then:

```sh
python -m personal_context.icloud_setup prepare
python -m personal_context.icloud_setup authenticate
python -m personal_context.icloud_setup verify
```

`prepare` does not contact Apple. It creates an encrypted **empty** dedicated
Rclone config and a local password helper. The helper derives a purpose-specific
config password from the unlocked archive key; it passes only that derived
password to Rclone over its password-command pipe. No extra plaintext key file is
created. Runtime directory permissions must be 0700 and config permissions 0600.
Protect and back up the archive key using your existing encrypted key policy.

Authentication requires a local interactive terminal and the registered USB key.
Create exactly `icloud`, choose `iclouddrive`, leave service `drive`, and enter
credentials there. Use the key's existing PIN; never generate a replacement PIN.
Do not paste passwords, PINs, configs or session tokens into chat. Keep encryption
on in Rclone's configuration menu. Rclone obscured passwords alone are not
at-rest encryption. ADP may require trusted-device approval and existing iCloud
web access. Do not disable security keys or ADP to make this work.

Reconnect later with `python -m personal_context.icloud_setup reconnect`. Tools
never initiate interactive auth, retry PIN failures or return raw provider logs.
No authentication, actual account access or cloud-server session transfer is
established by fixture tests or successful compilation. Official Rclone docs
mention a 30-day trust token; actual sessions may need attention sooner:
https://rclone.org/iclouddrive/ .

## Rclone terminal boundaries

The setup adapter permits fixed read commands only, validates the iclouddrive
backend and forces service drive. Terminal verification is independent of the
native-tag-aware MCP data tools. Do not use raw terminal reads as a workaround for
an MCP policy denial. The main MCP uses the Mac receiver described below.

## Native Finder tags, folder scopes and writer permissions

MCP data operations now require the Mac native receiver. Rclone's Drive backend
cannot expose Finder tags; a filename heuristic or local substitute tag store
cannot enforce the requested exclusion. Rclone remains installed for independent
terminal authentication/testing, but MCP does not fall back to its data commands.
The Mac must be awake and reachable for every file operation. Metadata reflects
the Mac's synced view; this does not prove instantaneous iCloud convergence.

Run `python3 scripts/install_icloud_native.py` **on the Mac**. This only installs
the stdlib receiver and an owner-only disabled config at
`~/.config/personal-context-bridge/icloud-native.json`; it does not inspect files.
The receiver command is
`~/.local/share/personal-context-bridge/bin/icloud-drive-receiver`.
Before enabling, verify the configured root is the intended authenticated Drive,
its native tags are synced, and native read/write permissions work using temporary
fixtures. Set `protected_tags` to a nonempty list of your protected native tag
names, for example `["Restricted", "Confidential"]` (fictional policy). The
receiver refuses access if this setting is missing, empty or invalid. Existing
installations must copy their current protection policy into this private setting
before updating the receiver; never replace it with an example policy. The installer
preserves existing configuration and leaves new configurations disabled with an
empty policy. Set local config `enabled` true when actual connection is authorized.
`permission` may be `reader` or `writer`; writer only adds native tag edits,
one-folder creation and regular-file moves. It has no delete/upload/content-edit
operation. Installation preserves an existing config. Never grant root permissions.

The local config `segments` maps names to root-relative folders, for example
`{"drive":"", "work":"Work", "school":"School"}` (fictional names).
Remove `drive` to restrict access to only named roots. Tool paths stay relative to
Drive root, and an empty list/search path uses the selected segment root. These
are backend scope boundaries, checked again for direct reads and writes. The
administrator changes this config locally; an MCP caller cannot broaden scopes.

On Ubuntu set `PERSONAL_CONTEXT_ICLOUD_NATIVE_ENABLED=1`,
`PERSONAL_CONTEXT_ICLOUD_NATIVE_TARGET` to the existing pinned SSH Mac target and
`PERSONAL_CONTEXT_ICLOUD_NATIVE_COMMAND` to the absolute installed receiver. If
omitted, target and command derive from the existing Apple-write transport.
Both connection gates remain disabled during preparation. No key or Apple session
is transferred to the Mac receiver. There is no remote shell interpolation of
filenames, tags, filters or sentence text: they travel only as bounded JSON stdin.

Tools list/search by folder segment, path/name substring, native tags (`all`/`any`),
extension and creation/modification date bounds. Dates are ISO dates at UTC midnight
or offset-aware timestamps; after is inclusive and before exclusive. Results default
to newest modification first, with optional oldest/name sorting. Searches scan at
most 2000 entries and depth 10; narrow scopes rather than silently claiming a full
search. Unknown tag metadata, special files and symlinks deny access.
Configured native `protected_tags` match trimmed Unicode-normalized names without case sensitivity.
Tagged folders protect descendants. Protected items cannot be retagged, moved,
read by exact path or passed into AI search. Adding a configured protected tag is permitted
and immediately hides that item; removing it through MCP is forbidden.

`smart_search_icloud_drive` selects up to ten files from a sentence using the
existing shared ChatGPT subscription, with at most forty allowed metadata
candidates. The local shortlist combines sentence terms and recent modifications.
Only name/folder/tag/date metadata is sent to inference. Results include optional
8 KiB UTF-8 excerpts retrieved locally after current tag/revision verification.
This is AI metadata retrieval, **not full file-body semantic search**. PDFs/Office
files receive metadata only. No embeddings endpoint, hosted file-search service,
paid API fallback or persistent plaintext content index is used.

Writer tools require inspected revisions. Folder creation requires the existing
parent's revision; file moves require source and destination-parent revisions.
Exclusive native rename refuses existing destinations and cross-device moves;
there is no copy/delete fallback. Moving whole folders is rejected. Tag edits
preserve unrelated tags and existing Finder color suffixes. Native tags are read
and written on held file descriptors, and read results are rechecked before
return. This protects against detected concurrent edits; the Mac filesystem and
remote iCloud clients do not provide an atomic global tag snapshot or inode-conditional
rename. Concurrent namespace replacement can occur between checking and mutation;
post-operation identity checks report uncertainty rather than claiming completion
or attempting a potentially destructive rollback. Do not run concurrent folder
reorganization during writer operations. After an
uncertain SSH write outcome, inspect both paths before a deliberate retry.
