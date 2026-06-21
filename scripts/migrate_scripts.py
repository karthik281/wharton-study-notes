"""One-off: move helper/tool scripts into scripts/ and fix their root-path resolution.

Core app modules (agent.py, panopto_client.py, notes_generator.py, file_processor.py,
canvas_client.py) stay in the project root. Each moved script resolves the repo root
via Path(__file__).resolve().parent -> needs .parent.parent once it lives in scripts/.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
SCRIPTS.mkdir(exist_ok=True)

MOVE = [
    "probe_video.py", "probe_video2.py", "diagnose_mapping.py", "check_new_sessions.py",
    "fix_corrupt_fnce529.py", "reorder_fnce.py", "discover_async.py", "regenerate_notes.py",
    "rename_folders.py", "download_videos.py", "process_async.py", "process_new_sessions.py",
]

OLD = "Path(__file__).resolve().parent"
NEW = "Path(__file__).resolve().parent.parent"

for name in MOVE:
    src = ROOT / name
    if not src.exists():
        print(f"absent: {name}")
        continue
    text = src.read_text(encoding="utf-8")
    if OLD in text and NEW not in text:
        text = text.replace(OLD, NEW)
        src.write_text(text, encoding="utf-8")
        fixed = " (path fixed)"
    else:
        fixed = ""
    shutil.move(str(src), str(SCRIPTS / name))
    print(f"moved: {name}{fixed}")

# Move this migration script itself last.
try:
    shutil.move(str(Path(__file__).resolve()), str(SCRIPTS / Path(__file__).name))
    print("moved: migrate_scripts.py (self)")
except Exception as exc:
    print(f"(self move skipped: {exc})")
print("done")
