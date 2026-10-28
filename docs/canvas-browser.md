# Firefox-backed student Canvas

A second institutional account can use the owner's existing Firefox Canvas sign-in on Ubuntu. It shares the encrypted archive and all Canvas read tools, but refreshes independently of the Mac token collector. No API token is created. This is browser-session-backed structured API collection, not a UI scraper or an autonomous login agent.

## Route

1. Sign into the institution's student portal in the configured private Firefox profile.
2. Open the portal's Canvas link and complete institution SSO/MFA interactively.
3. Once Canvas is authenticated, go directly to its HTTPS origin on later visits. The portal is only needed when SSO must be renewed.
4. The collector reads exact-host session cookies from Firefox's owner-only `sessionstore-backups/recovery.jsonlz4` in memory. It checks `/api/v1/users/self/profile` against a pinned user ID before collecting.
5. It performs same-origin GET API reads with bounded pagination. Conversation details require `auto_mark_as_read=false`. Cookies never enter source, logs, model prompts or archive records.
6. After collection finishes, existing validated batches enter the encrypted archive. On auth or collection failure the last snapshot remains. Ingestion errors may leave partial batch progress, so only a new successful status proves a finished run.

Firefox must have saved a current recovery session. Closing Firefox, private/container tabs, an expired SSO session or institution policy may require opening Canvas and signing in again. This adapter does not bypass MFA or school permissions. It does not launch external tools, submit coursework, open quizzes for attempts, change settings or send messages.

## Private configuration

Create a mode-0600 JSON file outside source at `~/.config/personal-context-bridge/canvas-browser.json` (or set `PERSONAL_CONTEXT_CANVAS_BROWSER_CONFIG`):

```json
{
  "account": "college",
  "base_url": "https://college.example.invalid",
  "expected_user_id": 123,
  "session_file": "/private/firefox/sessionstore-backups/recovery.jsonlz4",
  "status_file": "/private/state/canvas-browser-status.json",
  "download_files": true
}
```

Use the existing encrypted archive key and database environment. Run:

```sh
python -m personal_context.canvas_browser --config /private/canvas-browser.json --db /private/context.sqlite3
```

Linux `liblz4` is needed to decode Firefox's recovery format. The collector reads only the configured session file; it never modifies or clones the Firefox profile. Only default-context cookies for the exact Canvas host are accepted. PDF/DOCX/PPTX/plain-text downloads allow exact institutional file paths or signed Instructure, Canvas user-content, or S3 CDN URLs; external content is otherwise metadata only.

Configure an owner-managed user service named `personal-context-canvas-browser.service` with that command. A periodic timer is optional. The MCP refresh tool only requests this fixed service and never executes model-supplied commands. Run status contains no credentials. Keep the profile and archive private; use `ReadOnlyPaths` on the profile for the worker.

## Tools and coverage

- `canvas_browser_status`: independent browser collection/auth status and counts.
- `refresh_canvas_browser`: queue Ubuntu refresh; poll status for completion.
- `canvas_status`: per-account archive inventory.
- `list_canvas_records`: paginate all supported kinds using the account label.
- `canvas_grades`: reported enrollment totals or assignment scores; hidden/ungraded is null, never fabricated.
- `canvas_modules`, `canvas_module_items`: ordered module hierarchy and linked-page records.
- `canvas_inbox`, `get_canvas_record`: read conversations without changing upstream unread state.
- `search_canvas`, `upcoming_canvas_assignments`: account-filtered search and due dates.
- `read_canvas_file_text`, `canvas_pdf_info`, `view_canvas_pdf_page`: available file evidence.

Browser collection includes accessible historical courses as well as active courses. If the file index is disabled, it follows observed module File IDs individually and retains a non-authoritative file snapshot with explicit coverage. It extracts supported document and slide text without launching external tools.

The existing extended collector includes pages, syllabi, discussions/replies, submission feedback/history/rubrics, assignment groups, grading periods/standards, file/folder inventories, sections, users, navigation tabs, accessible quizzes/submissions, planner, missing work, groups and calendar windows. Access restrictions are recorded as unavailable, not empty. External LTI content is not guaranteed; Canvas Inbox is distinct from institutional Outlook/Hawkmail. "All data" means accessible supported Canvas records, not inaccessible grades or external platforms.

Use the machine-readable `canvas-browser-plan.csv` for narrow navigation/verification instructions. Local Laya can choose from observed DOM/ARIA navigation targets, but is not needed for deterministic API reads. Do not provide cookies, SSO forms, messages or grades as navigation prompts. Stop on ambiguous targets, login/MFA, unsupported new tabs or low confidence and re-observe rather than guessing.

CI requires isolated self-hosted Linux and macOS runners bearing `personal-context-isolated`. Missing capacity leaves jobs queued; no hosted fallback is permitted.
