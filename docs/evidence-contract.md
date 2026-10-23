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

## Evaluation preflight

`personal_context.evaluation_contract.validate_cases` checks a frozen benchmark's
explicit question components against requested fields and criteria, requires
source anchors and absence reasoning, and rejects overlaps with held-out source
clusters. This structural gate cannot discover a natural-language requirement
that was omitted from both the component list and rubric. Independently audit the
question decomposition and source meaning before answer generation.

`numeric_check` distinguishes scalar formatting from factual differences without
silently stripping units or converting percentages, currency periods or ratios.
Ambiguous values require semantic review. `account_calls` counts all planning,
answering and failed attempts with cached-input tokens retained inside total
input. Missing failed-call usage makes cost incomplete; it never becomes a
zero-cost success. Keep generation, query and evaluation costs separate.

## Sampled Health statistics

`health_projection.sampled_health_summary(items)` presents each existing
adapter-marked statistics object as one exact JSON fact, bound to its own original
index. It makes no inference call, rounds no values, removes no fields, and
performs no cross-date/device aggregation. All groups survive even when there are
more than sixteen. Non-statistic records require original reads and are counted
explicitly. This helper does not verify upstream calculations, deduplicate
samples, diagnose conditions, or establish phone-upload freshness.

Literal quotes are checked against individual original body, title, timestamp,
and metadata values (including nested values), rather than serialized joins or
object keys. Authentic literal text still
requires a separate semantic-support assessment.


## One-read context preparation

`summary_context.prepare_summary_context(source, value, items, refs, question='',
limit=8, max_characters=64000)` combines the complete summary, typed source catalog
and optional locally selected original excerpts. It makes no inference call.
A Health statistics object duplicated in the projected facts and catalog is
included once, only after exact equality is established. Every original identity
and statistics value remains available.

The character budget applies to the complete returned context, including selection
metadata. It may omit original reads, reporting their IDs/counts and incomplete
coverage. It never trims generated claims or catalog metadata to fit. A base
context that cannot fit requires existing paged summary/evidence reads. Stable IDs,
literal authenticity, and an efficient context pack do not prove semantic support.
