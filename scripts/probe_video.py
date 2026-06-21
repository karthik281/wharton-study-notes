"""Read-only probe: does Panopto expose downloadable video URLs for our sessions?

Does NOT download any video. Just inspects the DeliveryInfo JSON to report:
  - whether auth (cookie) is currently valid
  - stream URLs (HLS .m3u8 vs MP4) under Delivery.Streams
  - podcast/download streams under Delivery.PodcastStreams
  - IsDownloadable / download flags
"""

import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

server = os.environ["PANOPTO_SERVER"].strip().rstrip("/")
cookie = os.environ.get("PANOPTO_COOKIE", "").strip()
ids = [s.strip() for s in os.environ.get("PANOPTO_SESSION_IDS", "").split(",") if s.strip()]

print(f"server={server}  cookie_chars={len(cookie)}  n_session_ids={len(ids)}")
if not ids:
    raise SystemExit("No PANOPTO_SESSION_IDS configured")

sid = ids[0]
url = (
    f"https://{server}/Panopto/Pages/Viewer/DeliveryInfo.aspx"
    f"?deliveryId={sid}&invocationId=&isLiveNotes=false&refreshAuthCookie=true"
    f"&isActiveBroadcast=false&isEditing=false&isKollectiveAgentInstalled=false"
    f"&isEmbed=false&responseType=json"
)
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Cookie": cookie,
    "Accept": "application/json",
}
resp = requests.get(url, headers=headers, timeout=20)
print(f"HTTP {resp.status_code}  content-type={resp.headers.get('content-type')}")

ctype = resp.headers.get("content-type", "")
if "json" not in ctype:
    print("Response is NOT json (likely a login/SSO redirect -> cookie stale/invalid).")
    print("First 300 chars:")
    print(resp.text[:300])
    raise SystemExit(0)

data = resp.json()
d = data.get("Delivery", {})
print("\nDelivery top-level keys:", sorted(d.keys()))
print("SessionName:", d.get("SessionName"))
print("Duration(s):", d.get("Duration"))
print("IsDownloadable:", d.get("IsDownloadable"))

print("\n-- Streams --")
for s in d.get("Streams", []) or []:
    u = s.get("StreamUrl") or s.get("StreamHttpUrl")
    print(f"  tag={s.get('Tag')!r:20} type={'HLS' if u and '.m3u8' in u else ('MP4' if u and '.mp4' in u else '?')}  url={u}")

print("\n-- PodcastStreams --")
for s in d.get("PodcastStreams", []) or []:
    print(f"  {s.get('StreamUrl')}")

# Probe the podcast MP4 download endpoint (HEAD only -- no download)
pod = f"https://{server}/Panopto/Podcast/Download/{sid}.mp4"
try:
    h = requests.head(pod, headers=headers, timeout=20, allow_redirects=True)
    print(f"\nPodcast MP4 endpoint: HEAD {h.status_code}  type={h.headers.get('content-type')}  len={h.headers.get('content-length')}")
    print(f"  url: {pod}")
except Exception as exc:
    print(f"\nPodcast MP4 endpoint HEAD failed: {exc}")
