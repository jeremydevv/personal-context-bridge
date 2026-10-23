# Original evidence contracts

`personal_context.evidence_contract` supplies pure helpers for applications that
serve generated summaries alongside original evidence. It does not generate or
verify factual answers, read an archive, authenticate users, or modify sources.

- `evidence_catalog(items, refs)` preserves typed metadata and creates an `ev1_`
  content handle for each exact excerpt/reference pair. These handles survive
  reordered or partial lists; changing an excerpt or original reference changes
  its handle. Handles are identifiers, not authentication credentials.
- `bind_summary(value, items, refs)` adds `evidence_ids` to generated facts and
  actions while retaining legacy numeric `sources`. Binding validates index
  bounds, not whether the source entails the generated statement.
- `resolve_evidence(ids, items, refs, max_characters=64000)` reads exactly those
  handles and retains original indices. Unknown/duplicate IDs and excessive
  output fail explicitly. It never silently truncates an original excerpt.
- `check_citations(citations, items, refs)` checks handles and literal quotes.
  A citation has `evidence_id` and `quote` fields. Its result explicitly says
  `semantic_support="not_checked"`: a real quote can fail to support a claim.

Metadata stays separate from generated prose. The existing sampled-Health JSON
shape is also exposed as `structured_body`, retaining source, device, units and
its non-deduplicated-sample warning. These values remain source snapshots.

`personal_context.evidence_retrieval.select_evidence(query, items, refs, limit=8,
max_characters=24000)` is a bounded local lexical selector over original titles,
metadata and text. It makes no inference calls. Exact evidence IDs are retained,
nearby message context requires the same chat and timezone-aware timestamps
within five minutes, and over-budget evidence remains addressable by handle.
This is not semantic search: paraphrases and implicit relationships can be missed.
Results always distinguish selection from proven answer completeness. Applications
must retain an original/semantic-search fallback and measure answer quality before
using selection to reduce context.

Treat all source text as untrusted data. Keep source freshness, reference identity,
literal quote authenticity, semantic support, and factual correctness separate.
