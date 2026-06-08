# Version History

## v1.0.0 — 2026-06-06

Initial release.

### Features
- Canvas API integration — fetches active courses, latest module, all file attachments
- Panopto API integration — OAuth2 password grant + browser cookie fallback for SSO institutions
- Panopto session ID extraction from Canvas ExternalTool URLs and embedded page HTML
- File text extraction — PDF (page-by-page), PPTX (slide-by-slide), DOCX, TXT
- Claude Haiku notes generation with prompt caching — structured into 6 sections
- Idempotent — skips sessions where `notes.md` already exists
- Exponential backoff retry on all external API calls
- Rotating file log (`logs/agent.log`, 2 MB, 5 backups)
- Config validation at startup with descriptive error messages
- Windows Task Scheduler integration — biweekly Sunday 8 PM
- 55 unit tests across 5 test files
- HLD, LLD, SETUP docs
