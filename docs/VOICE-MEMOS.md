# Apple Voice Memos

Voice Memos follows the existing personal-context pattern: a read-only Mac
collector, protected retry spool and SSH delivery, the shared SQLCipher archive,
background processing, and read tools on the existing Personal Context MCP.
An optional `--source voice_memo` server exposes the same source tools separately.
No new account, calendar, browser authentication scraper, or cloud storage is used.

## Data flow

Enable `all_voice_memos` in the private Mac config. Full and fast sync both run
`voice-memos-sync`. The collector opens `CloudRecordings.db` in read-only mode,
reads stable recording IDs and dates, and extracts every text run from Apple's
`moov/trak/udta/tsrp` MP4 metadata, including timestamp attributes. It seeks around
the audio payload and bounds metadata parsing. The original Apple title remains
unchanged. Database and audio paths are confined to the configured recordings
root; changed files fail the snapshot and retry later.

Missing local audio and unsupported native transcripts are explicit states.
Original audio is streamed separately over SSH, verified against the snapshot's
SHA-256, and stored with the existing authenticated encrypted BlobStore. Audio
bytes never enter JSON record bodies or source control. Files over 1 GiB remain
explicitly unavailable under the size policy. Only metadata and transcript text
use the existing Mac retry spool (private owner-only storage).

Snapshots are additive: an empty, offline or not-yet-hydrated iCloud cache never
deletes previously archived memos. Therefore removing an Apple recording does
not automatically remove its archived history. The source status describes the
Mac cache, not iPhone/iCloud completeness. Apple does not document the database
or embedded transcript format as a public API; OS changes can require adapters.

## Processing and generated text

Run `personal_context.voice_memos_worker process --db /private/runtime/context.sqlite3`
with `PERSONAL_CONTEXT_KEY_FILE` set. Existing native transcripts are indexed
first. Missing transcripts use local faster-whisper on the complete encrypted
original. Plaintext audio exists only in an owner-only temporary directory,
removed on exit; Linux defaults to `/dev/shm` with a free-space check. Transcription
and embeddings require `pip install '.[voice]'`. Whisper/model downloads are
runtime caches outside the repository. Transcriptions may be inaccurate.

Summaries use the **shared** `personal_context.enrichment.EnrichmentClient.from_env()`
owned by the unified enrichment subsystem. No separate Voice Memos OAuth client
or credential store exists. Set `PERSONAL_CONTEXT_VOICE_SUMMARIES_ENABLED=1` once
that module is installed. Missing sign-in leaves transcripts and embeddings
working and reports pending auth; the worker retries on later runs.

The shared provider uses ChatGPT plan OAuth and the public `/v1/responses`
endpoint, `store=false`, `stream=true`, and completed-response/schema validation.
It never falls back to a separately billed API key. `/v1/messages` is not this
OpenAI endpoint. Subscription limits and authorization still apply. This plan
flow does not cover audio transcription or embedding endpoints.

Every character of a long transcript is sent through bounded map/reduce rather
than slicing the beginning. Generated title and summary are stored separately
and labeled generated/unverified, with model and generation time. Content-bound
source digests invalidate derived results when a recording changes. The shared
provider caches successful account/model/prompt/content-version requests; partial
or failed summaries never become successful cache entries. Source text is
untrusted data and is not executable instructions to the enrichment provider.

## Search and tools

- `search_apple_voice_memo`: keyword, semantic, or hybrid passage retrieval.
- `get_apple_voice_memo_record`: original metadata plus labeled generated analysis.
- `read_apple_voice_memo_transcript`: full text in pages; follow `next_offset` to eof.
- `apple_voice_memo_timeline`: recording dates in a bounded timezone-aware range.
- `apple_voice_memo_status`: source freshness and processing counts.
- `force_refresh_apple_voice_memos`: optional existing Mac sync request; acceptance
  is not completion and does not force Apple's iCloud download service.

Generic personal-context search also includes Voice Memo passages, and exact
`kind=voice_memo` reads return metadata plus a paginated transcript. Text offsets
are character offsets, not audio times. Native timestamp runs are retained in
the encrypted archive; no speaker identity is inferred.

Keyword retrieval uses encrypted SQLite FTS5. Semantic search is optional, runs
locally, and keeps vectors in the same encrypted archive. Configure
`PERSONAL_CONTEXT_VOICE_EMBED_MODEL=fastembed:BAAI/bge-small-en-v1.5` for CPU ONNX
embeddings; no separate vector database/service is required. FastEmbed's token
limit is checked: overflow text is recursively split and every window embedded,
then normalized mean pooling represents each passage. Hybrid search combines
keyword and vector rankings with reciprocal rank fusion. It excludes deleted
records, stale source digests, and vectors from other configured models. This is
a practical first implementation; retrieval quality on a real library must be
measured. The default model targets English.

An existing local Ollama embedding model can alternatively be named directly.
Only the fixed loopback `/api/embed` endpoint is used and truncation is disabled.
Do not point private embeddings at public services without separate authorization.

## Deployment

Use existing service identities and private config. See the opt-in config and
worker systemd templates in `examples/`. Preserve installed runtime overlays
when patching shared modules. Migrate the encrypted Store before restarting the
main MCP tunnel. Check installed MCP `tools/list` separately from ChatGPT's
published connector schema; a plugin refresh may still be needed. The existing
plugin/App IDs, sharing, permissions and other source connections stay intact.

Opening Voice Memos normally may start iCloud hydration. If its first-run welcome
or consent UI remains, complete that normally in the local signed-in session.
Do not modify TCC, reset CloudKit databases, toggle iCloud accounts or forge
welcome/consent preferences. Record empty-cache evidence honestly while allowing
all unrelated implementation and verification to finish.

## Research references

- [Apple sync behavior](https://support.apple.com/guide/voice-memos/vma6cc4d0571/mac).
- [Voice Memos MCP](https://github.com/jwulff/apple-voice-memo-mcp): native tsrp
  transcript extraction and optional local transcription.
- [Voice Memo tools](https://github.com/grmartin/macos-voice-memo-tools): MP4 atom
  layout and attributed-string run structure. Our parser is independently written.
- [whosaid](https://github.com/sblattj/whosaid): full-text plus local semantic/hybrid
  retrieval over timestamped transcripts.
- [FastEmbed](https://qdrant.tech/documentation/fastembed/fastembed-quickstart/):
  lightweight local ONNX embeddings.
- [ChatGPT plan inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
  and [limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).
