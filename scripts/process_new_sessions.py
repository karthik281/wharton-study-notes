"""Process this week's new sessions now (don't wait for the scheduled run).

Targets only the three real sessions, picking the COMPLETE recording in each case
(longest transcript, excluding "Not Complete" dupes). For each: generates notes and
prepends them to the correct existing course Notes.md (preserving newest-first order),
saves the transcript, and downloads the video.

Idempotent: skips notes if the session header already exists; skips video if complete.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

from panopto_client import PanoptoClient  # noqa: E402
from notes_generator import NotesGenerator  # noqa: E402
from download_videos import delivery_info, podcast_mp4_url, download  # noqa: E402

NOTES_ROOT = Path(r"C:\Users\raoka\Documents\WEMBA\Term 4")

# Each target: how to find it among discovered sessions + where its output goes.
TARGETS = [
    {
        "key": "Negotiation S5",
        "course_label": "OIDD/MGMT 6910 & LGST 8060 (51 Global) - Summer 2026",
        "must_contain": ["6/13", "6910"],
        "exclude": [],
        "course_dir": "OIDD-MGMT 6910 & LGST 8060 - Negotiations",
        "notes_file": "OIDD-MGMT 6910 & LGST 8060 - Notes.md",
        "folder": "05 13Jun26 - Multi-Issue Negotiation & CMO Debrief",
        "header": "6/13 7-10 am OIDD/MGMT 6910 & LGST 8060 (51 Global) - Summer 2026",
    },
    {
        "key": "FNCE S5",
        "course_label": "FNCE 7310 (51 Global) - Summer 2026",
        "must_contain": ["06/12", "fnce"],
        "exclude": ["not complete"],
        "course_dir": "FNCE 7310 - Global Valuation & Risk Analysis",
        "notes_file": "FNCE 7310 - Notes.md",
        "folder": "05 12Jun26 - Managing FX Risk",
        "header": "06/12 7am | FNCE 7310 (51 Global) - Summer 2026",
    },
    {
        "key": "FNCE S4",
        "course_label": "FNCE 7310 (51 Global) - Summer 2026",
        "must_contain": ["06/11", "fnce"],
        "exclude": ["not complete"],
        "course_dir": "FNCE 7310 - Global Valuation & Risk Analysis",
        "notes_file": "FNCE 7310 - Notes.md",
        "folder": "04 11Jun26 - Jaguar Case & Hedging Transaction Exposure",
        "header": "06/11 7pm | FNCE 7310 (51 Global) - Summer 2026",
    },
]


def pick_session(panopto, sessions, target):
    """Return (session_id, transcript) for the best-matching complete recording."""
    best = None  # (tlen, sid, transcript)
    for s in sessions:
        name = (s.get("SessionName") or "").lower()
        if not all(m.lower() in name for m in target["must_contain"]):
            continue
        if any(x in name for x in target["exclude"]):
            continue
        t = panopto.get_transcript(s["Id"]) or ""
        if best is None or len(t) > best[0]:
            best = (len(t), s["Id"], t)
    return (best[1], best[2]) if best else (None, None)


def prepend_notes(notes_path: Path, header: str, body: str) -> bool:
    existing = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""
    if f"<!-- session: {header} -->" in existing:
        print("    notes already present -- skipping notes")
        return False
    block = f"<!-- session: {header} -->\n\n{body.strip()}\n"
    new_text = block + ("\n\n---\n\n" + existing if existing.strip() else "\n")
    notes_path.write_text(new_text, encoding="utf-8")
    print(f"    notes prepended -> {notes_path.name}")
    return True


def main() -> None:
    panopto = PanoptoClient(server=os.environ["PANOPTO_SERVER"], cookie=os.environ.get("PANOPTO_COOKIE"))
    panopto.authenticate()
    generator = NotesGenerator(api_key=os.environ["ANTHROPIC_API_KEY"])

    sessions = panopto.get_all_sessions(max_results=20)

    for t in TARGETS:
        print(f"\n=== {t['key']} ===")
        sid, transcript = pick_session(panopto, sessions, t)
        if not sid:
            print("    ! no matching session found -- skipping")
            continue
        if not transcript.strip():
            print("    ! transcript empty -- skipping")
            continue
        print(f"    session {sid[:8]}  transcript {len(transcript)} chars")

        folder = NOTES_ROOT / t["course_dir"] / t["folder"]
        (folder / "materials").mkdir(parents=True, exist_ok=True)
        (folder / "materials" / "transcript.txt").write_text(transcript, encoding="utf-8")

        notes_path = NOTES_ROOT / t["course_dir"] / t["notes_file"]
        if not (notes_path.parent.exists()):
            print(f"    ! course dir missing: {notes_path.parent}")
            continue
        if f"<!-- session: {t['header']} -->" not in (
            notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""
        ):
            print("    generating notes...")
            body = generator.generate(
                course_name=t["course_label"], session_name=t["header"],
                transcript=transcript, materials=[],
            )
            prepend_notes(notes_path, t["header"], body)
        else:
            print("    notes already present -- skipping notes")

        # Video
        try:
            d = delivery_info(sid)
            url = podcast_mp4_url(d)
            if url:
                print("    downloading video...")
                download(url, folder / "materials" / "video.mp4")
            else:
                print("    ! no podcast MP4 -- skipping video")
        except Exception as exc:
            print(f"    !! video failed: {exc}")


if __name__ == "__main__":
    main()
