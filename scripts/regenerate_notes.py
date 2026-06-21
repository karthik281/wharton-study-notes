"""One-off: regenerate existing course Notes.md files from full local transcripts.

Rebuilds each course's combined notes by re-running the (now fixed) NotesGenerator
against each session's FULL transcript. Preserves the existing session headers, their
order, and any sections that have no transcript (e.g. "Async Modules"). Backs up each
original file to <name>.md.bak before overwriting.
"""

import os
import re
import sys
import shutil
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

sys.path.insert(0, str(PROJECT_DIR))
from notes_generator import NotesGenerator  # noqa: E402

NOTES_ROOT = Path(r"C:\Users\raoka\Documents\WEMBA\Term 4")

HEADER_RE = re.compile(r"<!-- session: (?P<name>.*?) -->")
HEADER_DATE_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})")
FOLDER_DATE_RE = re.compile(r"^\d+\s+(\d{2})(\d{2})(\d{2})\b")


def folder_date_map(course_dir: Path) -> dict[tuple[int, int], Path]:
    """Map (month, day) -> session folder, parsed from 'NN DDMMYY ...' folder names."""
    out: dict[tuple[int, int], Path] = {}
    for sub in sorted(course_dir.iterdir()):
        if not sub.is_dir():
            continue
        m = FOLDER_DATE_RE.match(sub.name)
        if not m:
            continue
        day, month, _yy = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        out[(month, day)] = sub
    return out


def split_sections(text: str) -> list[tuple[str, str]]:
    """Split combined notes into (session_name, body) pairs in original order."""
    matches = list(HEADER_RE.finditer(text))
    sections = []
    for i, m in enumerate(matches):
        name = m.group("name").strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip().strip("-").strip()
        sections.append((name, body))
    return sections


def regenerate_course(course_dir: Path, generator: NotesGenerator) -> bool:
    notes_files = list(course_dir.glob("*.md"))
    notes_files = [p for p in notes_files if not p.name.endswith(".bak")]
    if not notes_files:
        print(f"  ! no notes file in {course_dir.name}")
        return False
    notes_path = notes_files[0]
    course_name = course_dir.name

    original = notes_path.read_text(encoding="utf-8")
    sections = split_sections(original)
    fmap = folder_date_map(course_dir)

    rebuilt_blocks: list[str] = []
    for name, body in sections:
        dm = HEADER_DATE_RE.match(name)
        folder = fmap.get((int(dm.group(1)), int(dm.group(2)))) if dm else None

        if folder is None:
            print(f"  - keep (no transcript): {name}")
            new_body = body
        else:
            tpath = folder / "materials" / "transcript.txt"
            transcript = tpath.read_text(encoding="utf-8") if tpath.exists() else ""
            if not transcript.strip():
                print(f"  - keep (empty transcript): {name}")
                new_body = body
            else:
                print(f"  * regenerating: {name}  <-  {folder.name} ({len(transcript)} chars)")
                new_body = generator.generate(
                    course_name=course_name,
                    session_name=name,
                    transcript=transcript,
                    materials=[],
                ).strip()

        rebuilt_blocks.append(f"<!-- session: {name} -->\n\n{new_body}")

    new_text = "\n\n---\n\n".join(rebuilt_blocks) + "\n"

    backup = notes_path.with_suffix(".md.bak")
    shutil.copy2(notes_path, backup)
    notes_path.write_text(new_text, encoding="utf-8")
    print(f"  => wrote {notes_path.name} (backup: {backup.name})")
    return True


def main() -> None:
    generator = NotesGenerator(api_key=os.environ["ANTHROPIC_API_KEY"])
    for course_dir in sorted(NOTES_ROOT.iterdir()):
        if not course_dir.is_dir():
            continue
        print(f"\n=== {course_dir.name} ===")
        try:
            regenerate_course(course_dir, generator)
        except Exception as exc:  # keep going across courses
            print(f"  !! FAILED: {exc}")


if __name__ == "__main__":
    main()
