# Headless Collection and Refresh Tracking Implementation Plan

> **For agentic workers:** Execute the independent adapter, coordinator and MCP tasks in parallel under superpowers:dispatching-parallel-agents, then integrate and independently review the whole change. User explicitly approved implementation on 2026-10-25.

**Goal:** Implement headless-first source collection and truthful durable refresh tracking across Personal Context MCP.
**Architecture:** Keep existing encrypted ingestion/spool and source scopes. Add an encrypted refresh ledger and bounded worker, correlate collection/batch acknowledgements, and expose a common interface through existing and new MCP tools. Prefer direct provider Mail, native Contacts and snapshot-based Notes; unsupported capabilities remain explicit.
**Tech Stack:** Python, existing PrivateState/AES-GCM, SQLite/SQLCipher, macOS native frameworks, IMAP, existing MCP FastMCP.
**Spec:** docs/superpowers/specs/2026-10-23-unified-refresh-design.md, amended by user approval of direct provider Mail and database Notes extraction.

## Global Constraints
- No source scope expansion, native record writes, new paid provider or automatic login.
- Preserve private runtime patches, credentials, real data, operator-specific instruction overlays and operator-configured backup policies.
- No source bodies or identifiers in logs/public tests; fictional fixtures only.
- Collection completion requires correlated archive acknowledgement, never supervisor acceptance or unrelated timestamps.
- App state, device freshness and derived processing are separate outcomes.

## Review Focus
- Crash/replay and lost acknowledgement must not misattribute another run's data.
- Concurrent refreshes must not duplicate jobs or quit user-open apps.
- Native/database adapter IDs and data coverage must preserve current archived records.
- Offline, unconfigured and push-only sources must return honest actionable states.
- Legacy MCP clients and existing scheduled collectors must share tracking semantics.

### Task 1: Durable refresh coordinator and ingestion receipts
Owner: coordinator agent. Owns refresh_tracking.py, refresh_worker.py, refresh_request.py, message_refresh.py, cli.py, spool.py, sync_runner.py, store.py, and focused new coordinator/receipt tests.
Interfaces: request_refresh(sources: list[str], mode='recent')->dict; refresh_status(refresh_id: str)->dict; source_status(source='all', database=None)->dict in refresh_tracking.py. Sources use calendar/reminder/contact/mail/message/note/voice_memo/canvas/obsidian/saved_video/health/location/google_timeline/icloud_drive/summaries. Mac collection is source-only. Durable request IDs and child leases; worker command `python -m personal_context.refresh_worker --once`. Private config and keys live outside checkout. Source collector agent provides configure_headless(config) in headless_collect.py (sets explicit adapter options) and provider_mail_batches(config, timestamp, recent=False) in provider_mail.py. Default legacy adapters remain available, explicitly marked; direct providers require configured credentials.
- [x] Write failing fictional tests for durable offline queue, deduplication, expired leases, partial/error coverage, unchanged and empty snapshots, correlated ingestion/replay and source-only dispatch.
- [x] Run tests red, implement coordinator, worker/dispatch and scheduling hooks with bounded waits and sanitized errors.
- [x] Verify focused tests green, cross-source result attribution and persistent queue restart.

### Task 2: Headless source adapters
Owner: headless adapter agent. Owns contacts_collect.py, notes_collect.py, mail_collect.py, new headless_collect.py/provider_mail.py/notes_database.py/native Contacts helper and new focused adapter tests/docs. Do not edit cli.py.
- [x] Write failing tests for direct IMAP read-only scope and credentials protection, native Contacts field conversion, consistent Notes snapshots and unsupported-schema failures.
- [x] Implement headless adapters; preserve current IDs/scopes or fail explicitly before replacing a source. No silent GUI fallback on permission denial. Configure through configure_headless(config) and source collector functions; mail CLI integration consumed by Task 1.
- [x] Test native/database feasibility on Mac with aggregate-only evidence; preserve original data. Report authorization requirements separately; do not acquire/extract credentials.

### Task 3: MCP integration and capabilities
Owner: MCP agent. Owns main, Apple, Voice Memos, Canvas, Obsidian, iCloud Drive, location, Saved-video and iPhone Health/Travel MCP surfaces, service.py, new refresh_mcp.py and corresponding MCP tests/docs. No coordinator module edits. Also owns invocation receipts in Saved-video sync and the public Obsidian reconciliation script.
- [x] Write failing tests for common tools and legacy wrappers with durable IDs and additive status.
- [x] Add request_data_refresh, data_refresh_status, data_source_status on main and per-source surfaces; keep writes opt-in and read status read-only. Reuse Task 1 APIs (lazy imports for compatibility).
- [x] Preserve legacy fields and generic get-record/status compatibility; source wrappers request only their source. Include all push-only/manual/unconfigured sources in status, with source freshness separate from summary progress.
- [x] Verify actual stdio tool discovery/read status on fictional encrypted archive; no fake completion assertions.

Source implementation and focused fictional checks are complete. Deployment, live verification and publication remain separate gates below. Provider access and unsupported schemas retain explicit limitations.

### Task 4: Integration, deployment and whole-branch review
Owner: parent read-only orchestration; delegate necessary source corrections to owning agents.
- [ ] Review every implementation and run complete core/iPhone/build/privacy checks; resolve independent reviewer findings with regressions.
- [ ] Deploy only task modules preserving private overlays. Install bounded coordinator worker/schedule and explicit private source capability configuration.
- [ ] Verify real source-only refresh, archive receipts, app state and status tools; distinguish prepared/native/provider-permission limits.
- [ ] Update private coordination notes with exact verified results and outstanding externally gated actions.
- [ ] Publish only task files to origin/development and verify exact commit CI terminal result.
