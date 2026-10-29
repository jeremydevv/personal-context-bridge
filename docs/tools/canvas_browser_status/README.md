# canvas_browser_status

Ubuntu Firefox browser account collection is separate from Mac high-school Canvas.
Use `refresh_canvas_browser()` to request collection and `canvas_browser_status()`
to check its state, last successful ingestion and coverage. Queued is not complete.
For cached connector catalogs, use `force_refresh_canvas(account="<configured account>")`
and `canvas_status().browser_collection`. Omit account only for Mac collection.

The collector uses a nonblocking file lock across manual and scheduled runs.
Install the example service and timer as `personal-context-canvas-browser.service`
and `.timer`, preserving private configuration paths and existing hardening.
The timer runs hourly with up to two minutes jitter and catches missed runs.
Failures retry after 60 seconds, at most three starts per hour, with an 18-minute
per-attempt timeout. Expired login exits 2, suppressing retries for that activation;
status reports `authentication_required` and retains the previous success timestamp.
Sign in interactively through the existing browser; never put cookies in source.
A partial snapshot is not complete coverage: inspect per-course collection state.
