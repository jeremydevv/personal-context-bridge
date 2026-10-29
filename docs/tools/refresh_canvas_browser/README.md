# refresh_canvas_browser

Ubuntu Firefox browser account collection is separate from Mac high-school Canvas.
Use `refresh_canvas_browser()` to request collection and `canvas_browser_status()`
to check its state, last successful ingestion and coverage. Queued is not complete.
For cached connector catalogs, use `force_refresh_canvas(account="<configured account>")`
and `canvas_status().browser_collection`. Omit account only for Mac collection.

The collector uses a nonblocking file lock across manual and scheduled runs.
Install the example service and timer as `personal-context-canvas-browser.service`
and `.timer`, preserving private configuration paths and existing hardening.
The timer runs every 30 minutes with up to two minutes jitter and catches missed runs.
Failures retry after 60 seconds, at most three starts per hour, with an 18-minute
per-attempt timeout. Expired login exits 2, suppressing retries for that activation;
status reports `authentication_required` and retains the previous success timestamp.
Sign in interactively through the existing browser; never put cookies in source.
A partial snapshot is not complete coverage: inspect per-course collection state.

Pacing targets roughly nine minutes per full collection by default
(`refresh_target_seconds=540`, range 60–900). One shared request-start limiter
covers API calls, file downloads and redirects, including parallel file workers.
It uses the last successful total HTTP request count; the first run estimates
file/redirect traffic from prior API and file counts. A minimum interval of
0.0625 seconds prevents bursts; `request_interval_seconds` can increase it.
Network delays and changing coverage can extend the target duration. Status
includes the actual interval and total HTTP count; API progress counts remain
separate. This does not reduce the number of resources collected.

HTTP 429 stops the batch, preserves the previous archive, and reports
`rate_limited` with `retry_not_before`. Manual and scheduled attempts respect
that persisted cooldown. `Retry-After` seconds and HTTP dates are supported;
missing/invalid values use five minutes. No immediate service retry occurs.
