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
OUTPUT_DIR = Path(
    os.getenv("STUDY_NOTES_OUTPUT_DIR", r"C:\Users\raoka\Documents\WEMBA\Term 4")
)

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

_MONTHS = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
           7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}

# Standardized course folders. Each entry: identifying course numbers (year excluded),
# the folder name "<SHORT> <CODE> - <Name>", and the notes-file code prefix.
COURSE_CONFIG = [
    ({"7310"}, "FNCE 7310 - Global Valuation & Risk Analysis", "FNCE 7310"),
    ({"6360"}, "OIDD 6360 - Scaling Operations", "OIDD 6360"),
    ({"6910", "8060"}, "OIDD-MGMT 6910 & LGST 8060 - Negotiations", "OIDD-MGMT 6910 & LGST 8060"),
]


def _safe(name: str) -> str:
    return _SAFE_RE.sub("-", name).strip()


def _course_numbers(course_name: str) -> set[str]:
    """4-digit course codes in the name, excluding the year (e.g. 2026)."""
    return {n for n in re.findall(r"\b(\d{4})\b", course_name) if not 2000 <= int(n) <= 2099}


def resolve_course(course_name: str) -> tuple[str, str]:
    """Map a Panopto course name to (standard_folder_name, notes_code_prefix)."""
    nums = _course_numbers(course_name)
    for numbers, folder, code in COURSE_CONFIG:
        if nums & numbers:
            return folder, code
    # Fallback for unknown courses: derive the code from the name.
    m = re.search(r'([A-Z]+-?[A-Z]*\s*\d{4}(?:\s*&\s*[A-Z]+\s*\d{4})?)', course_name)
    code = m.group(1).strip() if m else _safe(course_name)
    return _safe(course_name), code


def course_dir_for(course_name: str) -> Path:
    folder, _ = resolve_course(course_name)
    d = OUTPUT_DIR / folder
    d.mkdir(parents=True, exist_ok=True)
    return d


_INCOMPLETE_RE = re.compile(r"not\s*complete|incomplete", re.I)
_SESSION_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")


def _dedup_key(session_name: str):
    """Group recordings of the same logical lecture: (course numbers, date)."""
    nums = frozenset(_course_numbers(session_name))
    m = _SESSION_DATE_RE.search(session_name)
    return (nums, (int(m.group(1)), int(m.group(2)))) if m else None


def dedup_sessions(panopto, sessions: list[dict]) -> list[dict]:
    """Filter discovered Panopto sessions before processing:

    1. Drop recordings flagged incomplete (e.g. names containing "Not Complete").
    2. When several recordings share the same course + date (duplicate captures),
       keep only the one with the longest transcript (the most complete capture).

    Order of the surviving sessions is preserved (newest-first).
    """
    filtered = []
    for s in sessions:
        name = s.get("SessionName", "")
        if _INCOMPLETE_RE.search(name):
            logger.info("Skipping incomplete recording: %s", name)
            continue
        filtered.append(s)

    # Group by logical-lecture key; sessions without a parseable date stay unique.
    groups: dict = {}
    for s in filtered:
        key = _dedup_key(s.get("SessionName", "")) or ("uniq", s.get("Id"))
        groups.setdefault(key, []).append(s)

    keep_ids = set()
    for group in groups.values():
        if len(group) == 1:
            keep_ids.add(group[0].get("Id"))
            continue
        best, best_len = None, -1
        for s in group:
            tlen = len(panopto.get_transcript(s.get("Id")) or "")
            if tlen > best_len:
                best, best_len = s, tlen
        for s in group:
            if s is not best:
                logger.info("Skipping duplicate recording (shorter transcript): %s",
                            s.get("SessionName", ""))
        keep_ids.add(best.get("Id"))

    return [s for s in filtered if s.get("Id") in keep_ids]


def session_dir(course_name: str, module_name: str) -> Path:
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    folder = OUTPUT_DIR / _safe(course_name) / f"{date_prefix} - {_safe(module_name)}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "materials").mkdir(exist_ok=True)
    return folder


def _date_label(session_name: str) -> str:
    """ddMonyy from a session name like '06/11 7pm | FNCE ...' -> '11Jun26'."""
    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", session_name)
    yref = re.search(r"\b20(\d{2})\b", session_name)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        yy = yref.group(1) if yref else datetime.now().strftime("%y")
        return f"{day:02d}{_MONTHS.get(month, '')}{yy}"
    now = datetime.now()
    return f"{now.day:02d}{_MONTHS[now.month]}{now.strftime('%y')}"


def _next_session_num(course_dir: Path) -> int:
    """Next zero-padded session number, based on existing '<NN> ...' folders."""
    nums = [int(m.group(1)) for d in course_dir.iterdir()
            if d.is_dir() and (m := re.match(r"^(\d{2})\s", d.name))]
    return (max(nums) + 1) if nums else 1


def derive_class_name(notes: str, fallback: str) -> str:
    """Pull the lecture topic from the notes (first descriptive H2), else fallback."""
    for line in notes.splitlines():
        line = line.strip()
        if line.startswith("## "):
            text = line[3:].strip()
            if re.match(r"^\d+\.", text) or text.lower().startswith(("session summary", "summary")):
                continue
            text = re.sub(r"^[^|]*\|\s*", "", text)   # drop a leading 'June 13, 7-10 AM | '
            text = text.strip(" -")
            if text:
                return _safe(text)[:80]
    return _safe(fallback)[:80]


def make_session_dir(course_name: str, session_name: str, class_name: str) -> Path:
    """Create a session folder named '<NN> <ddMonyy> - <Class Name>'."""
    course_dir = course_dir_for(course_name)
    folder = course_dir / f"{_next_session_num(course_dir):02d} {_date_label(session_name)} - {class_name}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "materials").mkdir(exist_ok=True)
    return folder


def course_notes_path(course_name: str) -> Path:
    """Return the single combined notes file for a course."""
    _, code = resolve_course(course_name)
    return course_dir_for(course_name) / f"{code} - Notes.md"


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

    # 1. Fetch transcript
    transcript = panopto.get_transcript(session_id)
    if not transcript:
        logger.warning("  No transcript available for session '%s' -- skipping", session_name)
        return

    # 2. Generate notes
    notes = generator.generate(
        course_name=course_name,
        session_name=session_name,
        transcript=transcript,
        materials=[],
    )

    # 3. Create the session folder (named from the derived lecture topic) and save materials
    class_name = derive_class_name(notes, session_name)
    folder = make_session_dir(course_name, session_name, class_name)
    (folder / "materials" / "transcript.txt").write_text(transcript, encoding="utf-8")
    logger.info("  Transcript saved (%d chars) -> %s", len(transcript), folder.name)

    # 4. Append to course-level notes.md
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

    sessions = dedup_sessions(panopto, sessions)
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
