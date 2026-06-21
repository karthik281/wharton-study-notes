"""Confirm the podcast MP4 is directly downloadable -- range request only, no full download."""
import os
from pathlib import Path
import requests
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

server = os.environ["PANOPTO_SERVER"].strip().rstrip("/")
cookie = os.environ.get("PANOPTO_COOKIE", "").strip()
sid = [s.strip() for s in os.environ["PANOPTO_SESSION_IDS"].split(",") if s.strip()][0]

headers = {"User-Agent": "Mozilla/5.0", "Cookie": cookie, "Accept": "application/json"}
url = (
    f"https://{server}/Panopto/Pages/Viewer/DeliveryInfo.aspx"
    f"?deliveryId={sid}&invocationId=&isLiveNotes=false&refreshAuthCookie=true"
    f"&isActiveBroadcast=false&isEditing=false&isKollectiveAgentInstalled=false"
    f"&isEmbed=false&responseType=json"
)
d = requests.get(url, headers=headers, timeout=20).json()["Delivery"]
mp4 = (d.get("PodcastStreams") or [{}])[0].get("StreamUrl")
print("podcast mp4 present:", bool(mp4))
if not mp4:
    raise SystemExit(0)

# Range request: first 1 MB only -- proves direct download works, fetches almost nothing.
r = requests.get(mp4, headers={"Range": "bytes=0-1048575"}, timeout=30, stream=True)
total = r.headers.get("Content-Range")  # e.g. 'bytes 0-1048575/1873421234'
print("HTTP", r.status_code)
print("content-type:", r.headers.get("content-type"))
print("content-range:", total)
got = 0
for chunk in r.iter_content(65536):
    got += len(chunk)
    if got >= 1048576:
        break
print(f"bytes pulled in test: {got}")
if total and "/" in total:
    size = int(total.split("/")[-1])
    print(f"full file size: {size/1e9:.2f} GB")
