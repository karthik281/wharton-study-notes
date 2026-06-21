"""One-off: force-overwrite the corrupted FNCE 5/29 video with a clean copy."""
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

from panopto_client import PanoptoClient
from download_videos import delivery_info, podcast_mp4_url, download, NOTES_ROOT

p = PanoptoClient(server=os.environ["PANOPTO_SERVER"], cookie=os.environ.get("PANOPTO_COOKIE"))
p.authenticate()

target = None
for s in p.get_all_sessions(max_results=20):
    name = (s.get("SessionName") or "")
    if "05/29 7am" in name and "FNCE" in name:
        target = s
        break

if not target:
    raise SystemExit("FNCE 05/29 7am session not found")

dest = NOTES_ROOT / "FNCE 7310 (51 Global) - Summer 2026" / "03 290526 Currency Exposures Taxonomy" / "materials" / "video.mp4"
print(f"force-overwriting: {dest}")
d = delivery_info(target["Id"])
url = podcast_mp4_url(d)
download(url, dest, force=True)
print("done")
