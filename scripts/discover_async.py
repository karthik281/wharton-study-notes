"""Read-only: broadly list Panopto sessions to identify async/module content."""
import os, re
from pathlib import Path
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")
from panopto_client import PanoptoClient

p = PanoptoClient(server=os.environ["PANOPTO_SERVER"], cookie=os.environ.get("PANOPTO_COOKIE"))
p.authenticate()
sessions = p.get_all_sessions(max_results=100)
print(f"discovered {len(sessions)} sessions\n")

# A "live session" looks like a dated lecture: contains M/D near the start.
LIVE_RE = re.compile(r"^\s*\d{1,2}/\d{1,2}\b|\|\s*\d{1,2}/\d{1,2}")

groups: dict[str, list] = {}
for s in sessions:
    name = s.get("SessionName", "")
    folder = s.get("FolderName", "") or "(no folder)"
    groups.setdefault(folder, []).append(name)

for folder in sorted(groups):
    print(f"### FOLDER: {folder}")
    for name in groups[folder]:
        kind = "LIVE " if LIVE_RE.search(name) else "ASYNC?"
        print(f"   [{kind}] {name}")
    print()
