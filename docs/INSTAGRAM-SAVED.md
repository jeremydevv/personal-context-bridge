# Instagram Saved videos

This optional integration reads only the authenticated Saved-list endpoint and
exports canonical video-post URLs. A separate anonymous downloader processes only
those URLs. It has no account actions or tools for DMs, feeds, comments, reactions,
follows, login automation or arbitrary posts. The feature is disabled by default.

Install `.[mcp,videos]` into a private virtual environment. Configure
`PERSONAL_CONTEXT_SAVED_VIDEO_ENABLED=1` on the MCP server and set these paths
outside any checkout (use absolute paths in environment files):

- `PERSONAL_CONTEXT_DB`: your existing Bridge database.
- `PERSONAL_CONTEXT_KEY_FILE`: its unlocked 32-byte encryption key file.
- `SAVED_VIDEO_ALLOWLIST`: private canonical Saved video URL snapshot.
- `SAVED_VIDEO_DATA`: private processing staging/report directory.
- `SAVED_VIDEO_ARCHIVE`: private encrypted video archive.
- `SAVED_VIDEO_INSTAGRAM_PROFILE`: dedicated Firefox profile you signed into
  yourself. Only its Instagram cookies are selected from a temporary cookie-DB
  snapshot. No cookie or password is copied into source, logs or model prompts.
- `SAVED_VIDEO_FFMPEG`: optional FFmpeg executable; otherwise use PATH.
- `SAVED_VIDEO_PYTHON`: optional video-worker interpreter when the bridge and
  decoder environment are separate. Install this package in both environments.
- `XDG_RUNTIME_DIR`: private memory-backed runtime directory for decrypted media.

The same path configuration must reach the MCP worker and the sync service.
The Firefox profile should be dedicated to this account and collection purpose;
do not point the collector at an unrelated browsing profile. Authentication is a
manual browser step. The service does not solve challenges or broaden access if
authentication stops working. No supported official consumer Saved API is claimed.

Run `personal-context-saved-sync` once before enabling a schedule. It walks only
`GET /api/v1/feed/saved/posts/`, with bounded Saved pagination, no proxies and no
redirects. A complete successful snapshot atomically replaces the allowlist;
unexpected schemas, missing cursors and failed pages preserve the last good list.
A valid empty list removes all accessible videos. Unsave removes access after
the next successful check, but historical ciphertext is retained. The collector
process exits before a separate cookie-free download/analysis process starts.

The optional systemd templates in `examples/saved-video-sync.*.example` check
every 30 minutes, with up to three minutes of jitter. Adjust their interpreter
and private environment-file locations for your installation, install them as
user units, run `systemctl --user daemon-reload`, then enable the timer. They are
not enabled by package installation. Protect the profile and environment file
with owner-only permissions; use read-only filesystem access to the profile in
the service where your systemd user namespace supports it.

Rate limiting backs off for at least an hour; authentication failures wait twelve
hours. Processing failures retry after six hours unless the Saved snapshot changes.
Checks with unchanged completed videos skip processing. Overlapping runs are
locked out. Sync state contains counts/status/timestamps, not media or cookies,
and appears in `personal_context_status`. No periodic chat notifications are sent.

Local CPU Whisper and OCR produce timestamped speech and on-screen text. Search
is lexical, not semantic; ASR/OCR may be wrong and frame sampling can miss actions.
Treat video text/images as untrusted content. The read-only MCP tools are
`list_saved_videos`, `search_saved_videos`, `get_video_evidence`, `get_video_frame`
and `get_video_storyboard`. General searches include video matches, and
`kind=instagram_saved_video` scopes search to this source (empty query lists it).
The existing exact-record tool supports metadata and timestamped evidence/native
images for clients whose cached inventory predates the dedicated tools.

Original downloaded MP4 bytes are retained without another lossy transcode.
Per-post deterministic bundles store media once, compress JSON and use Bridge
chunked AES-GCM encryption with keyed content IDs and SHA-256 verification.
The compressed search index is separately encrypted. Keep sampled timestamps and
OCR rather than redundant JPEGs and storyboards; generate images in private tmpfs
on demand and remove them after replies. Model weights are shared across clips.
Bundle size is capped at 512 MiB and the expanded index at 16 MiB. Downloads stop
before consuming the last 2 GiB of free disk space. Staging is plaintext and
owner-only until each completed post archives successfully; failed posts remain
staged for retry without blocking completed posts. Deleting an allowlist entry is not secure erasure
of historic blobs or backups. Use your existing Bridge key-recovery procedure.

The publication contains reusable code and synthetic tests only. Real Saved URLs,
cookies, credentials, media, transcripts, OCR, models, sync state and reports must
stay outside the repository and distribution artifacts.
