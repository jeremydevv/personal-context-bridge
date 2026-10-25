# Refresh reads through an existing macOS GUI session

macOS may allow an existing GUI LaunchAgent to read Calendar or Reminders while
rejecting the same executable over SSH. The optional refresh inbox keeps these
reads in that existing logged-in session. It does not open Calendar or Reminders,
write native records, acquire credentials, or grant permissions.

Copy [the LaunchAgent template](../examples/launchd/org.personalcontext.personal-context-refresh-inbox.plist)
to `~/Library/LaunchAgents/` on the Mac. Replace every `/ABSOLUTE/...` placeholder
with the private installed runtime, interpreter, helper directory, configuration,
and data directory. Plists do not expand `$HOME` or `~` in these values. Preserve
the interpreter, PATH, and dependency environment of the existing working reader.
Keep tokens and other credentials in their existing private files outside source.

The fixed label is `org.personalcontext.personal-context-refresh-inbox`. The
configuration must be an owner-only regular file, and the data directory must be
private. The SSH-side `mac_env.PERSONAL_CONTEXT_DATA_DIR` and LaunchAgent data
directory must match. Its trusted configuration path must match `mac_config`.

Load the customized plist for the current logged-in user:

```sh
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/org.personalcontext.personal-context-refresh-inbox.plist"
launchctl kickstart "gui/$(id -u)/org.personalcontext.personal-context-refresh-inbox"
```

In the Ubuntu coordinator's private configuration, enable the route only for
sources needing that session:

```json
{
  "sources": {
    "calendar": {"enabled": true, "capability": "mac", "mac_dispatch": "launchd"},
    "reminder": {"enabled": true, "capability": "mac", "mac_dispatch": "launchd"}
  }
}
```

Other sources retain the default `ssh` route. A source can separately select its
existing interpreter with `sources.<source>.mac_python`. No new source scope or
permission is enabled by installing the template.

SSH durably writes a metadata-only job and invokes the fixed label. The agent
collects exactly that source, using the existing global collection lock and spool.
The periodic check recovers queued jobs if a kickstart coincides with agent exit.
Only the matching request, attempt, source, and configuration digest can consume
its result. A supervisor acknowledgement means accepted work; completion still
requires the existing correlated archive receipts and successful coverage.

Jobs and terminal results remain private for replay protection. If an agent dies
after starting a job, a later drain records interruption rather than silently
rerunning that attempt. The coordinator then retries using a new attempt ID.
Changing configuration while work is queued produces `configuration_changed`;
request a new refresh after the private setup is ready. An absent GUI worker
reports waiting, and permission failures remain explicit. Local collection
completion does not prove upstream provider freshness.
