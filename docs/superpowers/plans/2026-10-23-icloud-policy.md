# Native-tag-aware iCloud Drive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose guarded native-tag retrieval and narrowly scoped writes.

**Architecture:** A Mac receiver checks tags on open file descriptors, rejects identification and protected ancestors, and performs exclusive native moves. Ubuntu exposes bounded typed tools and shared subscription reranking without a Rclone data fallback.

**Tech Stack:** Python, Darwin native xattrs/exclusive rename, MCP, existing encrypted subscription adapter.

**Spec:** docs/superpowers/specs/2026-10-23-icloud-policy.md

## Global Constraints
- Native Finder/iCloud tags; no managed-tag substitution.
- No delete, upload, overwrite or copy-delete fallback.
- No real iCloud reads/writes or authentication during preparation.
- Preserve the existing main plugin and shared subscription auth.

## Review Focus
- Unknown tags, protected ancestor and case variants must deny direct and filtered reads.
- All directory moves must fail; only regular files may move.
- Concurrent mutation must invalidate revisions and readback.
- Existing destinations and cross-device moves must never trigger replacement/copy.
- Provider output must never introduce paths or escape user filters.

### Task 1: Receiver and filters
Files: src/personal_context/icloud_native.py; tests/test_icloud_native.py.
Interfaces: NativeDrive(root, segments, tags).dispatch(request) -> dict; tags(fd) -> native tag list, tags.set(fd, values).
- [ ] Write fictional fixture tests for five review classes, scope boundaries, filters/date sorting and unknown operations; run and observe failure.
- [ ] Implement descriptor-based traversal and native tag checks, bounded enumeration, revision reads and three writer operations.
- [ ] Run focused tests and native Darwin tag/rename tests in Mac CI.

### Task 2: Transport, smart retrieval, tools
Files: src/personal_context/icloud_gateway.py, icloud_drive.py, icloud_drive_mcp.py; tests/test_icloud_gateway.py, test_icloud_mcp.py.
Interfaces: Drive().list/search/info/chunk/text/segments/write/smart; private fixed SSH JSON receiver.
- [ ] Test no-fallback, no-auth discovery, all writes annotated, candidate validation and content bounds; observe failures.
- [ ] Implement fixed transport and bounded shared enrichment; replace MCP data routing and preserve private Rclone setup adapter.
- [ ] Run focused tests and main core suite.

### Task 3: Publish and prepare
Files: docs/ICLOUD-DRIVE.md, .github/workflows/ci.yml; private runtime, plugin and project handoff.
- [ ] Document native deployment, permissions and offline behavior; mark native installation pending while Mac offline.
- [ ] Fresh review, local checks, development publish, exact CI including Mac fixture checks.
- [ ] Install Ubuntu modules, verify actual stdio catalog and blocked unauthenticated operations; update same private plugin and project notes.

Execution ruling: implement inline under the user's explicit setup authorization, without a redundant plan approval. No native user data connection is authorized yet. One fresh whole-change reviewer after implementation.
