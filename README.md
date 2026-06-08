# Wharton Study Notes Agent

Automatically fetches Panopto lecture transcripts and generates structured MBA study notes with Claude -- organised by course, one combined notes file per course.

---

## What it does

- Discovers recent Panopto lecture sessions using the Data.svc endpoint (works with SSO / browser cookie auth)
- Fetches the transcript for each session via the SRT endpoint
- Generates structured study notes using Claude Haiku
- Saves one `{COURSE CODE} - Notes.md` per course with all sessions appended, separated by `---`
- Skips sessions already in the notes file (idempotent -- safe to re-run)

---

## Quick Start

1. Copy `.env.example` to `.env` and fill in your credentials
2. Get your Panopto cookie from your browser (see [docs/SETUP.md](docs/SETUP.md))
3. Get your Anthropic API key from [console.anthropic.com](https://console.anthropic.com)
4. Install dependencies: `& "venv\Scripts\pip.exe" install -r requirements.txt`
5. Run: `& "venv\Scripts\python.exe" agent.py`

Full setup walkthrough: [docs/SETUP.md](docs/SETUP.md)

---

## Output Structure

```
output/
+-- OIDD 6360 (51 Global) - Summer 2026/
|   +-- OIDD 6360 - Notes.md           <- all sessions combined
|   +-- Session 01 - 2026-06-01 - Week 1 - Intro to Operations/
|   |   +-- materials/
|   |       +-- transcript.txt
|   +-- Session 02 - 2026-06-05 - Week 2 - Process Design/
|       +-- materials/
|           +-- transcript.txt
+-- FNCE 7310 (51 Global) - Summer 2026/
    +-- FNCE 7310 - Notes.md
    +-- Session 01 - 2026-06-05 - Capital Structure/
        +-- materials/
            +-- transcript.txt
```

Each `Notes.md` contains all sessions for that course, each with:
- **Session Summary** (3-5 bullets)
- **Key Concepts** (definitions and why they matter)
- **Frameworks and Models**
- **Case Studies / Examples**
- **Action Items / Takeaways**
- **Exam / Discussion Prep** (3-5 Q&A)

---

## Configuration

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | From [console.anthropic.com](https://console.anthropic.com) |
| `PANOPTO_SERVER` | Yes | Your institution's Panopto hostname, e.g. `upenn.hosted.panopto.com` |
| `PANOPTO_COOKIE` | Yes* | Browser cookie -- copy `.ASPXAUTH` value from DevTools |
| `PANOPTO_CLIENT_ID` / `_SECRET` / `_USERNAME` / `_PASSWORD` | Yes* | OAuth2 alternative to cookie auth |
| `MAX_SESSIONS_PER_RUN` | No | How many recent sessions to process (default: 20) |
| `CANVAS_URL` / `CANVAS_API_TOKEN` | No | Optional -- Canvas integration not used in primary flow |

*Either `PANOPTO_COOKIE` or all four OAuth2 vars are required.

---

## Running Tests

```powershell
& "venv\Scripts\python.exe" -m pytest tests/ -v
```

60+ tests, all passing.

---

## Sharing with Classmates

This agent works with any university that uses Panopto. To share with a classmate at any institution:

1. Give them the project folder
2. They set `PANOPTO_SERVER` to their institution's Panopto hostname in `.env`
3. They copy their own `.ASPXAUTH` cookie from their browser
4. They add their own `ANTHROPIC_API_KEY`
5. Run `& "venv\Scripts\python.exe" agent.py`

No code changes required.

---

## Documentation

- [docs/SETUP.md](docs/SETUP.md) -- step-by-step credential setup and scheduling
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) -- common issues and fixes
- [docs/HLD.md](docs/HLD.md) -- architecture and data flow
- [docs/LLD.md](docs/LLD.md) -- function reference and test coverage
