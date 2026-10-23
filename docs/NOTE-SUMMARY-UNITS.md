# Granular note-summary inputs

`personal_context.note_summary_units.note_summary_units(records)` prepares inputs
for a separate summary worker. It does not read a vault, run a model, install a
schedule, or change original notes. Callers supply records with `id`, `title`,
`body`, `digest` and a `reference` containing the source tool, vault and path.

Each note up to 6,000 characters stays separate. Longer notes split at Markdown
headings, then at paragraph or line boundaries where possible. Oversized lines
split at the character bound. Initial YAML frontmatter and fenced code are not
treated as headings. Every character remains in exactly one input excerpt;
excerpts never combine different notes. Small heading-only excerpts are retained
rather than silently discarded. This is a bounded Markdown scanner, not a full
CommonMark parser; unusual nested Markdown may require original-source inspection.

Each unit carries:

- A note identity and version digest.
- A vault/path locator, heading breadcrumb, inclusive line numbers and part number.
- Exact start/end character offsets into the unmodified supplied body.
- One input item and one source reference, suitable for zero-based fact citations.
- A source-specific summary profile and dense factual prompt.

Read files with `newline=''` if offsets must preserve CRLF exactly. Decode UTF-8
before calculating character offsets; offsets are not byte positions. Empty notes
retain an empty referenced excerpt. IDs remain stable when unrelated notes are
inserted; editing a note changes the input digest of all its excerpts so that they
refer to one source version. Heading edits or changed chunk boundaries can produce
new IDs. A caller should transactionally retire units absent from the next scan.

`DENSE_NOTE_PROMPT` requests concrete requirements, conditions, quantities, dates,
names, formulas, URLs, exceptions and explicit uncertainties. Workers must validate
the resulting JSON and citation indices, retain full originals separately, and
include `PROFILE` in the inference-cache key. Generated facts remain unverified;
smaller inputs and denser output do not prove completeness or improved accuracy.

Heading and path metadata should remain searchable even if the model omits them.
Compact search previews can limit displayed facts, provided an exact-read tool
returns the full summary and its source references.
