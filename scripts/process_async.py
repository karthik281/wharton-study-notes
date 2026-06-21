"""Download FNCE async lecture videos + transcripts and generate notes.

Pulls every session in the Panopto folder 'Asych. Videos FNCE7310-51g-Su26' into a
per-course 'Async Modules' folder (one subfolder per lecture, with video.mp4 +
transcript.txt) and appends generated notes to the course notes file.
"""
import os, re
from pathlib import Path
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

from panopto_client import PanoptoClient
from notes_generator import NotesGenerator
from download_videos import delivery_info, podcast_mp4_url, download

NOTES_ROOT = Path(r"C:\Users\raoka\Documents\WEMBA\Term 4")

ASYNC_FOLDER = "Asych. Videos FNCE7310-51g-Su26"   # Panopto folder name
COURSE_DIR = "FNCE 7310 - Global Valuation & Risk Analysis"
NOTES_FILE = "FNCE 7310 - Notes.md"
# Note label kept in original Panopto form so existing async note headers stay idempotent.
COURSE_LABEL = "FNCE 7310 (51 Global) - Summer 2026"


def lecture_key(name: str) -> float:
    m = re.search(r"Lecture\s+(\d+)\.(\d+)", name)
    return float(f"{m.group(1)}.{m.group(2)}") if m else 999.0


def lecture_label(name: str) -> str:
    m = re.search(r"Lecture\s+(\d+\.\d+)", name)
    return f"Lecture {m.group(1)}" if m else name


def append_notes(notes_path: Path, header: str, body: str) -> bool:
    existing = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""
    if f"<!-- session: {header} -->" in existing:
        print("    notes already present -- skipping notes")
        return False
    block = f"<!-- session: {header} -->\n\n{body.strip()}\n"
    new_text = (existing.rstrip() + "\n\n---\n\n" + block) if existing.strip() else block
    notes_path.write_text(new_text, encoding="utf-8")
    print(f"    notes appended -> {notes_path.name}")
    return True


def main() -> None:
    panopto = PanoptoClient(server=os.environ["PANOPTO_SERVER"], cookie=os.environ.get("PANOPTO_COOKIE"))
    panopto.authenticate()
    generator = NotesGenerator(api_key=os.environ["ANTHROPIC_API_KEY"])

    sessions = [s for s in panopto.get_all_sessions(max_results=100)
                if (s.get("FolderName") or "") == ASYNC_FOLDER]
    sessions.sort(key=lambda s: lecture_key(s.get("SessionName", "")))
    print(f"found {len(sessions)} async session(s) in '{ASYNC_FOLDER}'\n")

    notes_path = NOTES_ROOT / COURSE_DIR / NOTES_FILE
    async_root = NOTES_ROOT / COURSE_DIR / "Async Modules"

    for s in sessions:
        sid, name = s["Id"], s.get("SessionName", "")
        label = lecture_label(name)
        header = f"Async {label} | {COURSE_LABEL}"
        print(f"=== {label} ({name}) ===")

        transcript = panopto.get_transcript(sid) or ""
        if not transcript.strip():
            print("    ! transcript empty -- skipping")
            continue
        print(f"    transcript {len(transcript)} chars")

        folder = async_root / label / "materials"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "transcript.txt").write_text(transcript, encoding="utf-8")

        if f"<!-- session: {header} -->" not in (
            notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""
        ):
            print("    generating notes...")
            body = generator.generate(course_name=COURSE_LABEL, session_name=header,
                                      transcript=transcript, materials=[])
            append_notes(notes_path, header, body)
        else:
            print("    notes already present -- skipping notes")

        try:
            d = delivery_info(sid)
            url = podcast_mp4_url(d)
            if url:
                print("    downloading video...")
                download(url, folder / "video.mp4")
            else:
                print("    ! no podcast MP4 -- skipping video")
        except Exception as exc:
            print(f"    !! video failed: {exc}")


if __name__ == "__main__":
    main()
