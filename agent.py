#!/usr/bin/env python3
"""Wharton Study Notes Agent -- downloads lecture transcripts and generates notes."""

import logging
import os
import re
import sys
import time
from datetime import datetime
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
LOG_DIR = SCRIPT_DIR / "logs"
OUTPUT_DIR = SCRIPT_DIR / "output"

REQUIRED_ENV_VARS = ["ANTHROPIC_API_KEY"]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    log = logging.getLogger("study_notes")
    log.setLevel(logging.INFO)

    fh = RotatingFileHandler(LOG_DIR / "agent.log", maxBytes=2_000_000, backupCount=5)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


logger = _setup_logging()


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------
def with_retry(max_attempts: int = 3, delay: float = 2.0):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_attempts:
                        raise
                    wait = delay * (2 ** (attempt - 1))
                    logger.warning(
                        "%s attempt %d/%d failed: %s. Retrying in %.0fs...",
                        func.__name__, attempt, max_attempts, exc, wait,
                    )
                    time.sleep(wait)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------
def validate_config() -> None:
    """Validate required environment variables.

    Requires ANTHROPIC_API_KEY plus at least one Panopto auth method.
    Warns if no Panopto credentials but does not raise -- allows dry-run.
    """
    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    # Panopto auth check -- warn if missing
    panopto_ok = os.getenv("PANOPTO_COOKIE") or (
        os.getenv("PANOPTO_CLIENT_ID")
        and os.getenv("PANOPTO_CLIENT_SECRET")
        and os.getenv("PANOPTO_USERNAME")
        and os.getenv("PANOPTO_PASSWORD")
    )
    if not panopto_ok:
        raise EnvironmentError(
            "Panopto credentials required. "
            "Set PANOPTO_COOKIE or PANOPTO_CLIENT_ID/SECRET/USERNAME/PASSWORD in .env"
        )

    # Canvas is optional
    canvas_ok = os.getenv("CANVAS_URL") and os.getenv("CANVAS_API_TOKEN")
    if not canvas_ok:
        logger.info(
            "Canvas API not configured -- using Panopto-only mode. "
            "To enable Canvas: set CANVAS_URL and CANVAS_API_TOKEN in .env"
        )


# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------
_SAFE_RE = re.compile(r'[<>:"/\\|?*]')


def _safe(name: str) -> str:
    return _SAFE_RE.sub("-", name).strip()


def session_dir(course_name: str, module_name: str) -> Path:
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    folder = OUTPUT_DIR / _safe(course_name) / f"{date_prefix} - {_safe(module_name)}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "materials").mkdir(exist_ok=True)
    return folder


def panopto_session_dir(course_name: str, session_name: str) -> Path:
    """Create folder for Panopto-only session (materials only -- notes go to course level)."""
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    course_dir = OUTPUT_DIR / _safe(course_name)
    course_dir.mkdir(parents=True, exist_ok=True)
    # Count existing session folders to assign next session number
    existing = [d for d in course_dir.iterdir() if d.is_dir()]
    session_num = len(existing) + 1
    folder_name = f"Session {session_num:02d} - {date_prefix} - {_safe(session_name)}"
    folder = course_dir / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "materials").mkdir(exist_ok=True)
    return folder


def course_notes_path(course_name: str) -> Path:
    """Return path to the single combined notes file for a course."""
    course_dir = OUTPUT_DIR / _safe(course_name)
    course_dir.mkdir(parents=True, exist_ok=True)
    # Extract course code e.g. "OIDD 6360" from full course name
    match = re.search(r'([A-Z]+-?[A-Z]*\s*\d{4}(?:\s*&\s*[A-Z]+\s*\d{4})?)', course_name)
    code = match.group(1).strip() if match else _safe(course_name)
    return course_dir / f"{code} - Notes.md"


def append_session_notes(course_name: str, session_name: str, notes: str) -> Path:
    """Append a session's notes to the course-level notes.md, with a session header."""
    path = course_notes_path(course_name)
    header = f"<!-- session: {session_name} -->\n\n"
    separator = "\n\n---\n\n" if path.exists() else ""
    with open(path, "a", encoding="utf-8") as f:
        f.write(separator + header + notes.strip() + "\n")
    return path


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------
@with_retry(max_attempts=3)
def process_session(canvas, panopto, generator, course, module) -> None:
    from canvas_client import CanvasClient
    from file_processor import summarise_materials
    from notes_generator import NotesGenerator

    course_name = getattr(course, "name", str(course.id))
    module_name = getattr(module, "name", str(module.id))
    logger.info("Processing: '%s' / '%s'", course_name, module_name)

    folder = session_dir(course_name, module_name)
    notes_path = folder / "notes.md"

    if notes_path.exists():
        logger.info("Notes already exist for this session -- skipping: %s", notes_path)
        return

    # 1. Get module items
    items = canvas.get_module_items(module)
    logger.info("  %d module item(s) found", len(items))

    # 2. Download all files
    downloaded: list[Path] = []
    for item in items:
        if getattr(item, "type", "") == "File":
            path = canvas.download_module_item_file(item, folder / "materials")
            if path:
                downloaded.append(path)

    # 3. Find Panopto session IDs
    transcript = ""
    if panopto:
        panopto_ids = canvas.collect_panopto_ids(course, items)
        for sid in panopto_ids:
            t = panopto.get_transcript(sid)
            if t:
                transcript = t
                (folder / "materials" / "transcript.txt").write_text(
                    transcript, encoding="utf-8"
                )
                logger.info("  Transcript saved (%d chars)", len(transcript))
                break

    if not transcript:
        logger.info("  No transcript available for this session")

    # 4. Extract text from downloaded materials
    materials = summarise_materials(downloaded)

    # 5. Generate notes
    if not transcript and not materials:
        logger.warning("  No content to summarise for '%s' -- skipping notes", module_name)
        return

    notes = generator.generate(
        course_name=course_name,
        session_name=module_name,
        transcript=transcript,
        materials=materials,
    )

    notes_path.write_text(notes, encoding="utf-8")
    logger.info("  Notes saved: %s", notes_path)


@with_retry(max_attempts=3)
def process_panopto_session(panopto, generator, session_id: str, course_name: str, session_name: str) -> None:
    """Process a Panopto session -- appends notes to course-level notes.md."""
    from notes_generator import NotesGenerator

    logger.info("Processing: '%s' / '%s'", course_name, session_name)

    # Idempotency: check if this session's notes already exist in the course notes file
    combined_path = course_notes_path(course_name)
    session_marker = f"<!-- session: {session_name} -->"
    if combined_path.exists() and session_marker in combined_path.read_text(encoding="utf-8"):
        logger.info("Notes already exist for this session -- skipping: %s", session_name)
        return

    # Session folder for materials/transcript
    folder = panopto_session_dir(course_name, session_name)

    # 1. Fetch transcript
    transcript = panopto.get_transcript(session_id)
    if not transcript:
        logger.warning("  No transcript available for session '%s' -- skipping", session_name)
        return

    (folder / "materials" / "transcript.txt").write_text(transcript, encoding="utf-8")
    logger.info("  Transcript saved (%d chars)", len(transcript))

    # 2. Generate notes
    notes = generator.generate(
        course_name=course_name,
        session_name=session_name,
        transcript=transcript,
        materials=[],
    )

    # 3. Append to course-level notes.md
    saved_path = append_session_notes(course_name, session_name, notes)
    logger.info("  Notes appended: %s", saved_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    logger.info("Starting Wharton Study Notes agent")

    try:
        validate_config()
    except EnvironmentError as exc:
        logger.critical("Config error: %s", exc)
        sys.exit(1)

    # Initialise Panopto client (required)
    from panopto_client import PanoptoClient, PanoptoAuthError
    panopto_server = os.getenv("PANOPTO_SERVER", "upenn.hosted.panopto.com")
    panopto = PanoptoClient(
        server=panopto_server,
        client_id=os.getenv("PANOPTO_CLIENT_ID"),
        client_secret=os.getenv("PANOPTO_CLIENT_SECRET"),
        username=os.getenv("PANOPTO_USERNAME"),
        password=os.getenv("PANOPTO_PASSWORD"),
        cookie=os.getenv("PANOPTO_COOKIE"),
    )
    try:
        panopto.authenticate()
    except PanoptoAuthError as exc:
        logger.critical("Panopto auth failed: %s", exc)
        sys.exit(1)

    # Initialise notes generator
    from notes_generator import NotesGenerator
    generator = NotesGenerator(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Primary mode: Panopto-only (Data.svc session discovery)
    logger.info("Running Panopto-only mode")
    _run_panopto_mode(generator, panopto)


def _run_panopto_mode(generator, panopto) -> None:
    """Process sessions directly from Panopto using Data.svc session discovery."""
    max_sessions = int(os.getenv("MAX_SESSIONS_PER_RUN", "20"))
    logger.info("Discovering up to %d session(s) via Data.svc...", max_sessions)

    sessions = panopto.get_all_sessions(max_results=max_sessions)

    if not sessions:
        logger.warning("No sessions found. Check PANOPTO_COOKIE is valid and MAX_SESSIONS_PER_RUN is set.")
        return

    logger.info("Found %d session(s) to process", len(sessions))

    processed = 0
    skipped = 0

    for session in sessions:
        try:
            session_id = session.get("Id")
            session_name = session.get("SessionName", "")

            if not session_id:
                logger.warning("Session missing ID -- skipping: %s", session_name)
                skipped += 1
                continue

            # Fetch full metadata (course name) via DeliveryInfo
            info = panopto.get_session_info(session_id)
            course_name = info.get("CourseName") or session.get("FolderName") or "Lectures"
            session_name = info.get("SessionName") or session_name or f"Session {session_id[:8]}"

            process_panopto_session(panopto, generator, session_id, course_name, session_name)
            processed += 1
        except Exception as exc:
            logger.error("Failed to process session: %s", exc, exc_info=True)
            skipped += 1

    logger.info("Done. Processed %d session(s), skipped %d.", processed, skipped)


def _extract_course_name(session_name: str) -> str:
    """Extract course name from Panopto session name. Falls back to 'Lectures' if not found."""
    # Try to extract course code (e.g., "MGMT 6100" from session name)
    match = re.search(r"([A-Z]{4,6}\s*\d{4})", session_name)
    if match:
        return match.group(1).strip()

    # Try to extract first part before any dash or parenthesis
    match = re.match(r"([^-()]+)", session_name)
    if match:
        name = match.group(1).strip()
        if len(name) > 3:  # Avoid single-letter names
            return name

    return "Lectures"


if __name__ == "__main__":
    main()
