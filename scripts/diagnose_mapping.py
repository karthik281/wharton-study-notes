"""Diagnose the find_session_folder mapping for each configured session."""
import os, re
from pathlib import Path
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")
from panopto_client import PanoptoClient
from download_videos import find_session_folder, NOTES_ROOT

p = PanoptoClient(server=os.environ["PANOPTO_SERVER"], cookie=os.environ.get("PANOPTO_COOKIE"))
p.authenticate()
ids = [s.strip() for s in os.environ["PANOPTO_SESSION_IDS"].split(",") if s.strip()]

print("=== mapping per configured session ===")
for sid in ids:
    info = p.get_session_info(sid)
    name = info.get("SessionName", "")
    nums = re.findall(r"\b(\d{4})\b", name)
    folder = find_session_folder(name)
    rel = str(folder).replace(str(NOTES_ROOT) + os.sep, "") if folder else "<none>"
    print(f"  nums={nums}  {name[:45]:45} -> {rel}")

print("\n=== video.mp4 files on disk ===")
for f in sorted(NOTES_ROOT.rglob("video.mp4")):
    rel = str(f).replace(str(NOTES_ROOT) + os.sep, "")
    print(f"  {f.stat().st_size/1e9:5.2f} GB  {rel}")
