# Student Canvas archive

Canvas collection uses GET requests with your own student permissions. It does not
submit work, start quizzes, mark Inbox messages read, post discussions, launch LTI
tools or follow external module links. Keep tokens on the collecting machine.

The collector includes courses, assignments and basic grades, announcements,
Inbox, ordered modules/items, accessible Pages and front pages, syllabuses, own
submission text/comments/history and any returned rubric assessments, discussion
prompts and visible replies, assignment groups/weights/drop rules, grading periods
and standards, file/folder inventories, sections/course users/navigation, personal
planner items/notes/overrides, Canvas to-do/missing lists, group memberships, and
personal/active-course calendar events. Classic quiz metadata and own attempts are
collected where available. New Quizzes and external tool contents require their
own integration; a module link does not establish content access. Standalone
teacher-only rubric lists and late-policy management are not requested.

`search_canvas` searches original archived content. `get_canvas_record` reads an
exact result. `list_canvas_records` browses any kind, optionally filtering by
account or exact course ID, with limit/offset pagination. Use `submission` for
feedback, `discussion_entry` for replies, `assignment_group` for grading weights,
and `collection_state` for feature coverage. `file_inventory` contains metadata
and a link to the canonical `file` record where collected; PDF/DOCX extraction
remains opt-in in the portable collector. A `page` contains both HTML and text.

`canvas_status` and listing results distinguish successful empty snapshots from
unavailable or partial collection. HTTP403/404 preserves earlier snapshots and
their timestamps. Unexpected failures abort before ingestion. Missing replies
behind a post-first gate are not an empty discussion. Successful complete
snapshots retire removed records; retiring a course also retires its course
resources. Planner/calendar collection covers the preceding30days and following
180days, with explicit bounds; reconciliation only retires missing records inside
that window. Records outside it remain historical snapshots.

## Generated explanations

`canvas_summary_status` reports summary coverage separately from collection.
`canvas_search_explanations` retrieves AI-generated Canvas explanations, with
per-source pagination when no kind is specified. The optional shared structured
summary service must be installed and configured separately. Use `get_canvas_explanation` to inspect the summary, citation references and
paginated input evidence, then use original Canvas
record IDs to verify generated statements. Source content remains authoritative.

For shared summary adapters, extend the source list with
`canvas_resources.summary_kinds()` and the metadata allowlist with
`canvas_resources.SUMMARY_METADATA_KEYS`. Extension processing defaults to held;
set `PERSONAL_CONTEXT_CANVAS_EXTENDED_SUMMARIES=1` explicitly in both the summary
worker and MCP environments when ready. This flag does not start collectors or
resume syncing. Preserve complete body chunks, source IDs/digests and citation
validation through the existing summary pipeline. Do not run backfills or summary
jobs while a user-requested hold applies to that new data.
