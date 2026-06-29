"""Probe DeliveryInfo for one session: auth check + available MP4 stream URLs."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
import requests

SID = sys.argv[1] if len(sys.argv) > 1 else "3b81fdeb-9bd8-43c6-b61a-b471010b3131"
server = os.environ["PANOPTO_SERVER"].strip().rstrip("/")
cookie = os.environ.get("PANOPTO_COOKIE", "").strip()
H = {"User-Agent": "Mozilla/5.0", "Cookie": cookie, "Accept": "application/json"}

url = (f"https://{server}/Panopto/Pages/Viewer/DeliveryInfo.aspx?deliveryId={SID}"
       "&invocationId=&isLiveNotes=false&refreshAuthCookie=true&isActiveBroadcast=false"
       "&isEditing=false&isKollectiveAgentInstalled=false&isEmbed=false&responseType=json")
r = requests.get(url, headers=H, timeout=30)
j = r.json()
if j.get("ErrorCode"):
    print("AUTH/ERROR:", j.get("ErrorMessage"))
    sys.exit(1)
d = j.get("Delivery", {})
print("AUTH OK")
print("SessionName:", d.get("SessionName"))
print("Duration(s):", d.get("Duration"))
print("HasCaptions:", d.get("HasCaptions"))
print("\nPodcastStreams:")
for s in (d.get("PodcastStreams") or []):
    print("  ", s.get("StreamUrl"))
print("\nStreams (other):")
for s in (d.get("Streams") or []):
    u = s.get("StreamUrl") or ""
    print("  ", u[:120])
