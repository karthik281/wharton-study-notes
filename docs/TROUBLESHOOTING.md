# Troubleshooting -- Wharton Study Notes Agent

---

## 1. "Panopto auth failed" / authentication errors

**Symptom:** Agent logs `Panopto auth failed` or `401 Unauthorized` and exits.

**Cause:** Your `.ASPXAUTH` cookie has expired. Browser cookies typically last 24-48 hours.

**Fix:**
1. Open your Panopto site in Chrome/Edge and log in
2. Press **F12** -> **Application** tab -> **Cookies** -> your Panopto URL
3. Copy the full **Value** of `.ASPXAUTH`
4. Update `PANOPTO_COOKIE` in your `.env` file:
   ```
   PANOPTO_COOKIE=.ASPXAUTH=<new-value-here>
   ```
5. Run the agent again

---

## 2. "No sessions found" / empty session list

**Symptom:** Agent logs `No sessions found` and exits without processing anything.

**Possible causes and fixes:**

- **MAX_SESSIONS_PER_RUN too low:** If all sessions in the window have already been processed, increase the limit: `MAX_SESSIONS_PER_RUN=50`
- **Data.svc endpoint blocked:** Some institutions restrict access to `Services/Data.svc`. Check if you can browse `https://{your-server}/Panopto/Pages/Sessions/List.aspx` in a browser while logged in. If not, contact your IT department.
- **Cookie not set correctly:** Ensure the full cookie string is in `.env`, e.g. `.ASPXAUTH=abc123...` (include the cookie name prefix).
- **Wrong PANOPTO_SERVER:** Confirm your institution's Panopto hostname. Find it in the URL when you log in to Panopto.

---

## 3. Empty transcript / no transcript available

**Symptom:** Agent logs `No transcript available for session` and skips the session.

**Cause:** The lecture recording has no captions or the auto-generated captions were not enabled.

**What to check:**
- Open the session in your browser and look for the "CC" (closed captions) button in the Panopto player. If it is greyed out, no transcript exists.
- Some recordings are manually captioned and may appear 24-48 hours after the lecture.

**Workaround:** Re-run the agent after captions become available. The idempotency check will skip already-processed sessions, so re-running is safe.

---

## 4. Claude API error

**Symptom:** Agent logs `Error generating notes` or errors from the Anthropic SDK.

**Possible causes and fixes:**

- **Invalid API key:** Verify `ANTHROPIC_API_KEY` in `.env` starts with `sk-ant-` and matches the key shown at [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)
- **Billing issue:** Check your usage and credits at [console.anthropic.com](https://console.anthropic.com). The agent uses Claude Haiku which is low-cost, but an exhausted credit balance will fail all requests.
- **Rate limit:** If processing many sessions at once, you may hit rate limits. The agent retries 3 times with exponential backoff, but extreme cases may need `MAX_SESSIONS_PER_RUN` reduced.

---

## 5. Session processed again / notes duplicated

**Symptom:** A session you already have notes for gets processed again and duplicate content appears in the Notes.md file.

**Cause:** The session marker `<!-- session: {session_name} -->` was not found, likely because the session name changed between runs (e.g. Panopto updated the session title).

**Fix:**
1. Open the course `Notes.md` file and check the existing session marker
2. If the marker is present but with a slightly different name, the deduplication check works on exact name matching

**Prevention:** Avoid renaming Panopto sessions after the agent has processed them.

---

## 6. Notes file corrupt or duplicated sections

**Symptom:** The course `Notes.md` file has garbled content or the same session notes appear multiple times.

**Fix:** Delete the course `Notes.md` file and re-run the agent. All sessions will be reprocessed from scratch.

```powershell
# Example: delete notes for OIDD 6360 (adjust path to your STUDY_NOTES_OUTPUT_DIR)
Remove-Item "C:\Users\raoka\Documents\WEMBA\Term 4\Wharton Study Notes\OIDD 6360 (51 Global) - Summer 2026\OIDD 6360 - Notes.md"
```

Then re-run:
```powershell
& "venv\Scripts\python.exe" agent.py
```

The agent will regenerate notes for all sessions. Set `MAX_SESSIONS_PER_RUN` high enough to cover all sessions in the course.

---

## 7. "Missing required environment variables" at startup

**Symptom:** Agent exits immediately with `Config error: Missing required environment variables: ANTHROPIC_API_KEY`

**Fix:** Ensure your `.env` file exists and contains the required variable:
```
ANTHROPIC_API_KEY=sk-ant-...
```

If `.env` does not exist, create it from the example:
```powershell
Copy-Item .env.example .env
```

---

## 8. Task Scheduler runs but nothing happens

**Symptom:** The scheduled task fires but no new notes appear and `logs/agent.log` is not updated.

**Check:**
1. Verify the script path in Task Scheduler is correct and absolute
2. Open the task in Task Scheduler, click **History** to see the last run status
3. Run the agent manually to confirm it works: `& "venv\Scripts\python.exe" agent.py`
4. Check that the `.env` file is in the same folder as `agent.py`

---

## Getting help

Check `logs/agent.log` for detailed error messages -- the log captures all warnings and errors with timestamps. Most issues are auth-related (expired cookie) or configuration-related (missing env var).
