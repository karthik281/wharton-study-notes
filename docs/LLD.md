# Low Level Design -- Wharton Study Notes Agent

## Module Structure

```
Wharton Study Notes/
+-- agent.py               # Orchestrator -- main entry point
+-- panopto_client.py      # Panopto session discovery + transcript client
+-- canvas_client.py       # Canvas REST API wrapper (optional)
+-- file_processor.py      # PDF / PPTX / DOCX text extraction
+-- notes_generator.py     # Claude notes generation
+-- docs/
|   +-- SETUP.md           # Credential setup guide
|   +-- HLD.md             # Architecture and data flow
|   +-- LLD.md             # Function reference and test coverage
|   +-- TROUBLESHOOTING.md # Common issues and fixes
+-- scripts/
|   +-- run_agent.bat      # Task Scheduler entry point
+-- tests/
|   +-- test_agent.py
|   +-- test_canvas_client.py
|   +-- test_panopto_client.py
|   +-- test_file_processor.py
|   +-- test_notes_generator.py
+-- logs/                  # Gitignored -- rotating agent.log
+-- .env / .env.example
+-- requirements.txt
+-- README.md
+-- VERSION.md
```

---

## panopto_client.py

### `PanoptoClient(server, client_id, client_secret, username, password, cookie)`

| Method | Signature | Notes |
|---|---|---|
| `authenticate()` | `-> None` | Cookie takes precedence over OAuth2 |
| `_authenticate_oauth()` | `-> None` | POST to `/Panopto/oauth2/connect/token`, grant_type=password |
| `_authenticate_cookie()` | `-> None` | Sets Cookie header directly |
| `_ensure_auth()` | `-> None` | Auto-refreshes OAuth token; cookie auth has no expiry |
| `get_all_sessions(max_results)` | `(int=20) -> list[dict]` | POST /Services/Data.svc/GetSessions; returns {Id, SessionName, FolderName} |
| `get_session_info(session_id)` | `(str) -> dict` | GET DeliveryInfo.aspx; returns {Id, SessionName, CourseName, Duration, HasCaptions} |
| `get_transcript(session_id)` | `(str) -> str` | API first, SRT fallback; returns plain text |
| `_scrape_transcript_from_html(session_id)` | `(str) -> str` | GET GenerateSRT.ashx; strips sequence numbers and timestamps |
| `search_sessions(query)` | `(str, int=5) -> list[dict]` | Stub -- logs warning; use get_all_sessions() instead |

**Session discovery (Data.svc) request body:**
```json
{
  "queryParameters": {
    "query": "",
    "sortColumn": 1,
    "sortAscending": false,
    "maxResults": 50,
    "startIndex": 0,
    "folderID": null,
    "bookmarked": false,
    "sessionListOnly": true,
    "getFolderData": true,
    "isSharedFolderSearch": false
  }
}
```
Response: `data["d"]["Results"]` -- each result has `DeliveryID`, `SessionName`, `FolderName`.

**SRT transcript format:** Strips sequence numbers (lines that are pure digits), timestamp lines (containing `-->`), and auto-generated disclaimer lines. Joins remaining lines with spaces.

**Auth strategy priority:**
1. If `PANOPTO_COOKIE` is set -> cookie auth (no expiry management needed)
2. If all OAuth vars set -> OAuth2 password grant (auto-refresh on token expiry)
3. Neither -> `PanoptoAuthError`

---

## agent.py

### `validate_config()`
Checks `ANTHROPIC_API_KEY` (raises `EnvironmentError` if missing).
Checks at least one Panopto auth method is configured (raises `EnvironmentError` if neither cookie nor OAuth vars present).
Canvas vars are optional -- logs info if absent.

### `course_notes_path(course_name) -> Path`
Builds `<OUTPUT_DIR>/{safe_course}/{COURSE CODE} - Notes.md`.
Extracts course code via regex `([A-Z]+-?[A-Z]*\s*\d{4}...)` from the full course name.
Falls back to sanitised course name if no code found.
Creates the parent directory.

### `append_session_notes(course_name, session_name, notes) -> Path`
Appends to course-level notes file.
Prepends `\n\n---\n\n` separator if the file already exists.
Wraps content with `<!-- session: {session_name} -->` header for idempotency.

### `panopto_session_dir(course_name, session_name) -> Path`
Creates `<OUTPUT_DIR>/{safe_course}/Session {NN} - {date} - {safe_session}/materials/`.
Session number assigned by counting existing subdirectories + 1.

### `session_dir(course_name, module_name) -> Path`
Creates `<OUTPUT_DIR>/{safe_course}/{YYYY-MM-DD} - {safe_module}/materials/`.
Used for Canvas-mode sessions.

### `process_panopto_session(panopto, generator, session_id, course_name, session_name)`
Decorated with `@with_retry(max_attempts=3)`.

Flow:
1. Check `<!-- session: {session_name} -->` in course Notes.md -> skip if present
2. Create session folder via `panopto_session_dir`
3. Fetch transcript; skip session if empty
4. Save transcript.txt to materials/
5. Generate notes -> append to course Notes.md

### `_run_panopto_mode(generator, panopto)`
Calls `panopto.get_all_sessions(max_results=int(MAX_SESSIONS_PER_RUN))`.
For each session: calls `panopto.get_session_info(session_id)` to get course name.
Calls `process_panopto_session(...)`.

### `main()`
Exit codes: `0` = success, `1` = config/fatal error.

---

## file_processor.py

| Function | Input | Output |
|---|---|---|
| `extract_pdf_text(path)` | PDF file | Text per page with `[Page N]` labels |
| `extract_pptx_text(path)` | PPTX file | Text per slide with `[Slide N]` labels |
| `extract_docx_text(path)` | DOCX file | Paragraphs joined with double newline |
| `extract_text(path)` | Any file | Routes by extension; empty string if unsupported |
| `summarise_materials(paths, max_chars)` | `list[Path]` | `list[{name, text}]` -- skips empty/unsupported |

---

## notes_generator.py

### `NotesGenerator(api_key, model="claude-haiku-4-5-20251001")`

| Method | Notes |
|---|---|
| `generate(course_name, session_name, transcript, materials, max_tokens)` | Returns Markdown string |

**Notes structure (enforced by system prompt):**
1. Session Summary (3-5 bullets)
2. Key Concepts (definition + why it matters)
3. Frameworks & Models
4. Case Studies / Examples
5. Action Items / Takeaways
6. Exam / Discussion Prep (3-5 Q&A)

---

## Retry Strategy

```
Attempt 1 -> fail -> wait 2s
Attempt 2 -> fail -> wait 4s
Attempt 3 -> fail -> raise
```

Applied to: `process_session`, `process_panopto_session`

---

## Test Coverage

| File | Class | Cases |
|---|---|---|
| test_panopto_client.py | `TestAuthentication` | OAuth success/failure, cookie, prefer cookie, fallback OAuth, no credentials |
| test_panopto_client.py | `TestTranscript` | Joined text, 404, missing key, skip empty lines |
| test_panopto_client.py | `TestGetAllSessions` | Returns list, respects max_results, empty results, request error, deduplication |
| test_panopto_client.py | `TestGetSessionInfo` | Returns metadata, request error fallback, short name fallback |
| test_panopto_client.py | `TestSRTTranscript` | Parses SRT correctly, empty SRT, strips disclaimer, search_sessions stub |
| test_canvas_client.py | `TestPanoptoIdRegex` | Viewer URL, embed URL, no match, case-insensitive |
| test_canvas_client.py | `TestCanvasClient` | Panopto ID from item, from HTML, latest module, dedup, skip existing download, non-file item |
| test_file_processor.py | `TestExtractPdfText` | Multi-page, skip empty pages, exception |
| test_file_processor.py | `TestExtractPptxText` | Slide text, exception |
| test_file_processor.py | `TestExtractDocxText` | Paragraphs, exception |
| test_file_processor.py | `TestExtractText` | Routes PDF/PPTX/DOCX, reads TXT, unsupported |
| test_file_processor.py | `TestSummariseMaterials` | Filter unsupported, include supported, skip empty, truncate |
| test_notes_generator.py | `TestNotesGenerator` | No content placeholder, Anthropic call, materials in prompt, caching, model, truncation |
| test_agent.py | `TestSafeFilename` | Forbidden chars, normal chars, whitespace |
| test_agent.py | `TestSessionDir` | Creates dir, path contains names |
| test_agent.py | `TestValidateConfig` | All present, missing canvas (ok), missing Anthropic key, missing Panopto creds |
| test_agent.py | `TestProcessSession` | Skip existing notes, save notes |
| test_agent.py | `TestCourseNotesPath` | OIDD code, FNCE code, creates directory, fallback, MGMT code |
| test_agent.py | `TestAppendSessionNotes` | No leading separator, separator on second, content preserved |
| test_agent.py | `TestIdempotency` | Skips existing session, processes new session |

Run: `& "venv\Scripts\python.exe" -m pytest tests/ -v`
