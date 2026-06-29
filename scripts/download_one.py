"""Download a single Panopto session's podcast MP4 to an explicit destination.

Usage: download_one.py <session_id> "<dest_path.mp4>"
Resumable via HTTP Range; signed URL fetched immediately before download.
"""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
import requests

SID = sys.argv[1]
DEST = Path(sys.argv[2])
server = os.environ["PANOPTO_SERVER"].strip().rstrip("/")
cookie = os.environ.get("PANOPTO_COOKIE", "").strip()
H = {"User-Agent": "Mozilla/5.0", "Cookie": cookie}


def delivery():
    url = (f"https://{server}/Panopto/Pages/Viewer/DeliveryInfo.aspx?deliveryId={SID}"
           "&invocationId=&isLiveNotes=false&refreshAuthCookie=true&isActiveBroadcast=false"
           "&isEditing=false&isKollectiveAgentInstalled=false&isEmbed=false&responseType=json")
    r = requests.get(url, headers={**H, "Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    j = r.json()
    if j.get("ErrorCode"):
        raise RuntimeError(f"DeliveryInfo error: {j.get('ErrorMessage')}")
    return j.get("Delivery", {})


def mp4_url(d):
    for s in (d.get("PodcastStreams") or []):
        u = s.get("StreamUrl")
        if u and ".mp4" in u:
            return u
    return None


d = delivery()
url = mp4_url(d)
if not url:
    print("ERROR: no podcast MP4 available", flush=True)
    sys.exit(1)

DEST.parent.mkdir(parents=True, exist_ok=True)
head = requests.get(url, headers={**H, "Range": "bytes=0-0"}, timeout=30, stream=True)
head.raise_for_status()
cr = head.headers.get("Content-Range", "")
total = int(cr.split("/")[-1]) if "/" in cr else None
head.close()

existing = DEST.stat().st_size if DEST.exists() else 0
if total and existing >= total:
    print(f"Already complete ({total/1e9:.2f} GB): {DEST}", flush=True)
    sys.exit(0)

mode = "ab" if existing else "wb"
headers = {**H}
if existing:
    headers["Range"] = f"bytes={existing}-"
    print(f"Resuming at {existing/1e9:.2f} GB", flush=True)

print(f"Downloading -> {DEST}  (total {total/1e9:.2f} GB)" if total else f"Downloading -> {DEST}", flush=True)
with requests.get(url, headers=headers, timeout=120, stream=True) as r:
    r.raise_for_status()
    done = existing
    next_mark = done + 25 * 1024 * 1024
    with open(DEST, mode) as f:
        for chunk in r.iter_content(1024 * 1024):
            if not chunk:
                continue
            f.write(chunk)
            done += len(chunk)
            if done >= next_mark:
                pct = f"{100*done/total:.0f}%" if total else "?"
                print(f"  {done/1e9:.2f} GB ({pct})", flush=True)
                next_mark = done + 25 * 1024 * 1024
print(f"DONE: {DEST} ({DEST.stat().st_size/1e9:.2f} GB)", flush=True)
