"""Debug raw HTTP responses for a Panopto session."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()
import requests

SID = sys.argv[1] if len(sys.argv) > 1 else "3b81fdeb-9bd8-43c6-b61a-b471010b3131"
server = os.getenv("PANOPTO_SERVER", "upenn.hosted.panopto.com")
cookie = os.getenv("PANOPTO_COOKIE")
print("Cookie present:", bool(cookie), "len:", len(cookie or ""))

s = requests.Session()
if cookie:
    s.headers["Cookie"] = cookie
s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# DeliveryInfo
url = (f"https://{server}/Panopto/Pages/Viewer/DeliveryInfo.aspx?deliveryId={SID}"
       "&invocationId=&isLiveNotes=false&refreshAuthCookie=true&isActiveBroadcast=false"
       "&isEditing=false&isKollectiveAgentInstalled=false&isEmbed=false&responseType=json")
r = s.get(url, timeout=20)
print("\nDeliveryInfo status:", r.status_code)
print("Body[:500]:", r.text[:500])

# SRT
srt = f"https://{server}/Panopto/Pages/Transcription/GenerateSRT.ashx?id={SID}&language=0"
r2 = s.get(srt, timeout=20)
print("\nSRT status:", r2.status_code, "len:", len(r2.text))
print("SRT[:300]:", r2.text[:300])
