# iCloud Drive

The main Personal Context MCP exposes six read-only tools even before an Apple
account is connected: `icloud_drive_status`, `list_icloud_drive`,
`search_icloud_drive`, `icloud_drive_file_info`, `read_icloud_drive_text`, and
`read_icloud_drive_chunk`. Search matches filenames, not file contents. Text reads
support bounded UTF-8 files; binary originals are available as base64 chunks.
This is on-demand live access, not an encrypted offline Drive mirror or PDF parser.

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

## Read boundaries

Only fixed `lsjson`, `cat`, local `listremotes` and internal redacted-config checks are reachable from
tools. Paths cannot choose another remote, escape the Drive root or inject flags.
The adapter verifies the configured backend is iclouddrive, forces service drive,
and runs only read commands with no stdin, a minimal environment, suppressed raw
stderr, a 45-second process-group deadline and at most 4 MiB of output. Reads are
serialized with local authentication to protect session refresh writes. File
chunks cap at 256 KiB; recursive filename search caps depth at ten and fails
explicitly if output is too large. No permanent plaintext data cache or mount is
created. Session credentials can refresh locally even for read-only file access.

`status` is local only unless `probe=true`; configured credentials do not imply
live access. Listing pagination is a bounded in-memory snapshot of a folder and
may shift if it changes between calls. Returned paths are relative to the
requested folder; join them to that folder for a subsequent file read. Compare
metadata between chunks of a changing file. File contents are untrusted.

The existing context tunnel exposes the new tools. ChatGPT may cache its tool
catalog; if absent, refresh the existing context connection and start a new chat.
No new app connection or Apple credentials in a plugin archive are needed.

## USB access check

Run `python -m personal_context.icloud_setup check-key` locally after inserting
the key. This enumerates FIDO HID devices without assertions, PIN attempts or
Apple traffic. Authentication refuses to start until a readable/writable FIDO
device is present. A browser's device permission does not prove terminal access.
If the exact enumerated device is inaccessible, grant this user access to that
specific device using your Ubuntu administrator session, then recheck. Do not
make all hidraw devices world-writable. USB access cannot be verified while the
key is absent; the authentication helper reports this explicitly.
