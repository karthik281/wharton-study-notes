# Setup Guide -- Wharton Study Notes Agent

This guide walks you through setting up the agent from scratch. Estimated time: 15 minutes.

---

## 1. Prerequisites

- **Python 3.11 or later** -- download from [python.org](https://www.python.org/downloads/)
- **Anthropic account** -- sign up at [console.anthropic.com](https://console.anthropic.com)
- **Panopto access** -- you must be enrolled at a university that uses Panopto for lecture recordings

---

## 2. Installation

Copy (or clone) the project folder to your machine, then open a terminal in that folder.

```powershell
# Create virtual environment
python -m venv venv

# Install dependencies
& "venv\Scripts\pip.exe" install -r requirements.txt
```

---

## 3. Get your Panopto cookie

The agent authenticates to Panopto using a browser session cookie. This works with SSO (Okta, Azure AD, etc.) without needing API client access.

### Chrome / Edge

1. Open your institution's Panopto site (e.g. `upenn.hosted.panopto.com`) and log in
2. Press **F12** to open DevTools
3. Click the **Application** tab
4. In the left sidebar, expand **Cookies** and click your Panopto URL
5. Find the cookie named `.ASPXAUTH` (or `PanoptoSiteAuth` on some instances)
6. Click it and copy the full **Value** from the bottom panel

### Firefox

1. Log in to Panopto
2. Press **F12** > **Storage** tab > **Cookies** > your Panopto URL
3. Copy the **Value** of `.ASPXAUTH`

Your `.env` entry should look like:

```
PANOPTO_COOKIE=.ASPXAUTH=abc123xyz...verylongvalue...
```

> **Cookie expiry:** Browser cookies typically expire after 24-48 hours of inactivity.
> When the agent starts logging "Panopto auth failed", re-copy the cookie from your browser.

---

## 4. Get your Anthropic API key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Navigate to **Settings -> API Keys**
3. Click **Create Key**, give it a name (e.g. `Study Notes Agent`)
4. Copy the key -- it starts with `sk-ant-`

> Keep your API key private. Never share it or commit it to version control.

---

## 5. Create your .env file

Copy the example file and fill in your values:

```powershell
Copy-Item .env.example .env
```

Then open `.env` in a text editor and fill in:

```
ANTHROPIC_API_KEY=sk-ant-...your-key-here...
PANOPTO_SERVER=upenn.hosted.panopto.com
PANOPTO_COOKIE=.ASPXAUTH=...your-cookie-here...
MAX_SESSIONS_PER_RUN=20
```

For a first-time backfill of older sessions, set `MAX_SESSIONS_PER_RUN=50` (or higher).

---

## 6. Test run

```powershell
& "venv\Scripts\python.exe" agent.py
```

The agent will:
1. Authenticate to Panopto using your cookie
2. Discover the most recent sessions (up to `MAX_SESSIONS_PER_RUN`)
3. Fetch transcripts for each session
4. Generate study notes using Claude
5. Save notes to `output/`

Watch the terminal for progress. Any errors appear in `logs/agent.log`.

---

## 7. What to expect in output/

After a successful run, the `output/` folder looks like:

```
output/
+-- OIDD 6360 (51 Global) - Summer 2026/
|   +-- OIDD 6360 - Notes.md          <- combined notes for all sessions
|   +-- Session 01 - 2026-06-05 - Week 1 - Intro/
|   |   +-- materials/
|   |       +-- transcript.txt
|   +-- Session 02 - 2026-06-05 - Week 2 - Optimization/
|       +-- materials/
|           +-- transcript.txt
+-- FNCE 7310 (51 Global) - Summer 2026/
    +-- FNCE 7310 - Notes.md
    +-- Session 01 - 2026-06-05 - Lecture 1/
        +-- materials/
            +-- transcript.txt
```

Each `{COURSE CODE} - Notes.md` file contains all session notes for that course, separated by `---`.

---

## 8. Schedule biweekly runs (Windows)

Register a Task Scheduler job to run the agent automatically every two weeks:

```powershell
schtasks /create /tn "Wharton Study Notes" `
  /tr "C:\Users\raoka\Documents\Ideas\Agents\Wharton Study Notes\scripts\run_agent.bat" `
  /sc weekly /mo 2 /d SUN /st 20:00 /f
```

Check the task is registered:

```powershell
schtasks /query /tn "Wharton Study Notes" /fo list
```

Trigger a manual run at any time:

```powershell
schtasks /run /tn "Wharton Study Notes"
```

> Remember to refresh your Panopto cookie before the scheduled run if it has been more than 48 hours.

---

## 9. First-time backfill

If you want to process older sessions from earlier in the semester:

1. Open `.env` and set `MAX_SESSIONS_PER_RUN=100` (or higher for a full semester)
2. Run the agent: `& "venv\Scripts\python.exe" agent.py`
3. After the backfill completes, reset `MAX_SESSIONS_PER_RUN=20` for normal runs

The agent is idempotent -- sessions that already have notes in the course `.md` file are skipped, so re-running is safe.

---

## Sharing with classmates

This agent works with any university using Panopto. To share with a classmate:

1. Give them the project folder
2. They change `PANOPTO_SERVER` in `.env` to their institution's Panopto hostname
3. They copy their own `.ASPXAUTH` cookie and Anthropic API key into `.env`
4. Run `& "venv\Scripts\python.exe" agent.py`

No other changes needed.
