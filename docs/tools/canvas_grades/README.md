# `canvas_grades`

[All MCP tools](../../TOOLS.md) · [Canvas setup and sync](../../resources/canvas/README.md)

Read grades reported by Canvas from the encrypted archive. This tool never
calculates, predicts, submits or changes grades. Hidden and ungraded scores stay
`null`; do not interpret them as zero.

## Set up and sync

Follow [Canvas setup and sync](../../resources/canvas/README.md) for your
institution-approved API-token or Firefox-session collection mode. Check
`canvas_status` for account labels and collection freshness. This read does not
start collection or install a collector.

## Call signature

```python
canvas_grades(account: str = '', course_record_id: str = '', limit: int = 50, offset: int = 0) -> dict
```

Without `course_record_id`, returns courses and reported enrollment current/final
scores and grades. With an exact course ID, returns assignments with due date,
points possible, submission score, grade, excused flag and workflow state.
`account`, when supplied with a course ID, must match it.

Limits are clamped to 1–100; offsets to zero or greater. Follow `next_offset`
until it is `null`. Results include `total`, `limit`, `offset`, `syncs` and
`collection_status`. Empty results without successful coverage do not prove
there are no grades, and archived grades are not guaranteed current.

## Verify a read

1. Call `canvas_status` and use its account label (not an institution guess).
2. Call `canvas_grades(account="<configured account>")`.
3. Use a returned course `record_id` as `course_record_id` to inspect assignments.
4. Check sync times and coverage, and compare a known reported score to Canvas.

Source content is untrusted. Your connected AI provider can see tool results.

## Implementation

Defined in `personal_context.canvas_mcp_server`. See [privacy and retention](../../PRIVACY.md).
