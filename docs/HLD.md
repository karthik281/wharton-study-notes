# High Level Design -- Wharton Study Notes Agent

## Overview

A biweekly Python agent that authenticates to Panopto via browser cookie, discovers recent lecture sessions, fetches their transcripts, and generates structured study notes with Claude. One combined `{COURSE CODE} - Notes.md` file is maintained per course, with all sessions appended in order.

---

## Architecture

```
+----------------------------------------------------------------------+
|                     Windows Task Scheduler                            |
|              Every 2 weeks, Sunday 8 PM (local time)                 |
+-----------------------------+----------------------------------------+
                              | runs scripts/run_agent.bat
                              v
+----------------------------------------------------------------------+
|                           agent.py                                    |
|                        (orchestrator)                                 |
|                                                                       |
|  +------------------+   +--------------------+   +-----------------+ |
|  | panopto_client   |   | notes_generator    |   | output/         | |
|  |                  |   | (Claude Haiku API) |   |                 | |
|  | - cookie auth    |   |                    |   | per-course      | |
|  | - Data.svc       |   | - transcript ->    |   | Notes.md files  | |
|  |   session list   |   |   study notes      |   |                 | |
|  | - SRT transcript |   |                    |   |                 | |
|  +------------------+   +--------------------+   +-----------------+ |
+----------------------------------------------------------------------+
```

---

## Data Flow

```
1. Task Scheduler fires scripts/run_agent.bat
2. agent.py loads .env
3. validate_config() -- fail fast if ANTHROPIC_API_KEY or Panopto creds missing
4. PanoptoClient authenticates via browser cookie (.ASPXAUTH)
5. get_all_sessions(max_results=MAX_SESSIONS_PER_RUN)
   POST /Panopto/Services/Data.svc/GetSessions
   Returns: newest-first list of {DeliveryID, SessionName, FolderName}
6. For each session:
   a. get_session_info(session_id)
      GET /Panopto/Pages/Viewer/DeliveryInfo.aspx?deliveryId={id}&responseType=json
      Returns: {SessionName, CourseName (from SessionGroupLongName)}
   b. Idempotency check: skip if <!-- session: {name} --> in course Notes.md
   c. get_transcript(session_id)
      - Try: GET /Panopto/api/v1/sessions/{id}/transcripts/formatted
      - Fallback: GET /Panopto/Pages/Transcription/GenerateSRT.ashx?id={id}&language=0
   d. Save transcript.txt to session materials folder
   e. NotesGenerator sends transcript to Claude -> Markdown notes
   f. Append notes to <output-dir>/{CourseName}/{COURSE CODE} - Notes.md
7. Logs written to logs/agent.log with rotation
```

---

## External Dependencies

| Service | Purpose | Auth |
|---|---|---|
| Panopto (institution hosted) | Session discovery and transcripts | Browser cookie (.ASPXAUTH) |
| Anthropic Claude API | Notes generation | API key |
| Canvas API | Optional -- not used in primary flow | Personal access token |

---

## Output Structure

Default output directory: `C:\Users\raoka\Documents\WEMBA\Term 4\Wharton Study Notes`
Override with `STUDY_NOTES_OUTPUT_DIR` in `.env`.

```
<output-dir>/
+-- OIDD 6360 (51 Global) - Summer 2026/
|   +-- OIDD 6360 - Notes.md           <- all sessions combined
|   +-- Session 01 - 2026-06-01 - Intro to Operations/
|   |   +-- materials/
|   |       +-- transcript.txt
|   +-- Session 02 - 2026-06-05 - Process Design/
|       +-- materials/
|           +-- transcript.txt
+-- FNCE 7310 (51 Global) - Summer 2026/
    +-- FNCE 7310 - Notes.md
    +-- Session 01 - 2026-06-05 - Capital Structure/
        +-- materials/
            +-- transcript.txt
```

---

## Scheduling

- **Trigger:** Windows Task Scheduler -- every 2 weeks, Sunday at 8:00 PM
- **Idempotent:** If `<!-- session: {name} -->` already exists in the course Notes.md, that session is skipped
- **MAX_SESSIONS_PER_RUN:** Controls how many recent sessions are fetched per run (default: 20; set higher for initial backfill)

---

## Failure Modes

| Failure | Behaviour |
|---|---|
| Missing ANTHROPIC_API_KEY | sys.exit(1) immediately with clear log |
| Missing Panopto credentials | sys.exit(1) immediately with clear log |
| Panopto auth failure | Log critical error, sys.exit(1) |
| Cookie expired | Auth fails -- re-copy cookie from browser |
| No sessions found via Data.svc | Log warning, agent exits gracefully |
| SRT transcript unavailable | Session skipped, logged as warning |
| Claude API error | Retry 3x with exponential backoff |

---

## Future Enhancements

- Telegram notification when new notes are ready
- Automatic cookie refresh via browser automation
- Cross-session concept linking ("this relates to Week 3's Porter framework")
- Push notes to Notion or Obsidian
- Support for multiple institutions in one run
