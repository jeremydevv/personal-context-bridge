# Public distribution plan

Deliver the existing personal context engine as reusable source in a fresh public
repository. Preserve Apple Calendar, Reminders, Contacts, Mail, Messages, Notes,
Canvas, Health, OwnTracks, Timeline imports, and opt-in Obsidian note operations.
Do not copy archive data, credential files, deployment configs, logs, backup files,
installed plugin IDs, account identifiers, or private Git history.

1. Copy only reviewable source and synthetic tests. Audit hardcoded identifiers.
2. Make private locations and sender settings configurable. Keep write operations
   opt-in and require explicit vault selection.
3. Add setup and fictional demo commands that create keys and encrypted databases
   outside the checkout, plus source configuration and client examples.
4. Supply a portable Canvas collector where the original Mac-only collector is
   unavailable. Preserve complete-snapshot semantics and restrict credential use.
5. Document authentication, upstream licenses, platform requirements, encryption,
   retention, and optional background services for every source.
6. Run all unit/integration tests, authenticated HTTP receiver tests, MCP protocol
   calls, package builds, a release privacy check, and a fresh-clone install.
7. Commit only reviewed files on development, publish under the requested owner,
   and verify public visibility and the remote commit.

Acceptance: a new user can run the demo after cloning without any existing
accounts; can configure their own sources without editing personal constants;
and receives a repository and package containing no private runtime artifacts.
Live macOS/iPhone permission prompts must be completed on the user's own devices.
