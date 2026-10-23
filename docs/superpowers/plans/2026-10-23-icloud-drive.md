# iCloud Drive preparation

Goal: prepare the existing main Personal Context MCP for read-only live iCloud Drive access, leaving Apple authentication to the user later.

Architecture: a narrow Rclone adapter exposes status, one-folder listing, bounded filename search, metadata, UTF-8 text and base64 chunks. No arbitrary commands, remote names, uploads, deletions, mounts, persistent plaintext caches or authentication tools. The pinned community libfido2 build and an encrypted dedicated config live outside source. The existing tunnel/plugin identity stays intact.

Tasks:
- [x] Write failing tests for missing authentication, path/command isolation, output/time bounds, safe errors, and MCP tool registration.
- [x] Implement adapter and tools; preserve existing source/runtime differences.
- [x] Build pinned Rclone with libfido2, run scoped race tests, prepare encrypted empty config and local auth launcher.
- [x] Deploy additive runtime changes and verify real stdio catalog and unauthenticated calls; update existing private plugin instructions if needed.
- [x] Run regressions/privacy checks, publish task files to development, update private handoff and shared progress.

Security decisions: use the existing unlocked archive key to derive a separate Rclone config password; never expose credentials through MCP or raw child errors. Child processes receive a minimal environment, fixed flags and bounded memory/time. Authentication and USB-key access remain local and interactive. File data is untrusted and returned only on explicit reads. Apple session portability and actual-account compatibility remain unverified until authentication; no automatic transfer is enabled.

Verified: 317 main tests (one Mac skip), 19 iPhone tests, 11 focused Drive tests, Rclone native race tests and real encrypted-config/backend-isolation checks. Existing Saved-video suite: 39 pass, four fail because the local ffmpeg launcher points to an absent unrelated installation. Fresh installed stdio tools and unauthenticated responses verified; plugin 1.7.1 saved privately. Actual-account/USB login, cross-server portability and ChatGPT cached-catalog refresh remain unverified.
