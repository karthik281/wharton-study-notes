"""Read-only: list recent Panopto sessions and their readiness (video + transcript)."""
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

from panopto_client import PanoptoClient  # noqa: E402

p = PanoptoClient(server=os.environ["PANOPTO_SERVER"], cookie=os.environ.get("PANOPTO_COOKIE"))
p.authenticate()

sessions = p.get_all_sessions(max_results=20)
print(f"discovered {len(sessions)} sessions (newest first)\n")
print(f"{'#':>2}  {'video':>5} {'caps':>4} {'tlen':>6}  session")
for i, s in enumerate(sessions, 1):
    sid = s.get("Id")
    info = p.get_session_info(sid)
    # full delivery for encode-complete flag
    try:
        import requests
        url = (f"https://{os.environ['PANOPTO_SERVER'].rstrip('/')}/Panopto/Pages/Viewer/DeliveryInfo.aspx"
               f"?deliveryId={sid}&responseType=json&refreshAuthCookie=true")
        d = requests.get(url, headers={"Cookie": os.environ.get('PANOPTO_COOKIE',''), "Accept":"application/json",
                                       "User-Agent":"Mozilla/5.0"}, timeout=20).json().get("Delivery", {})
        vid = bool(d.get("IsPodcastEncodeComplete"))
        caps = bool(d.get("HasCaptions"))
    except Exception as exc:
        vid, caps = "?", f"err:{exc}"
    tlen = len(p.get_transcript(sid) or "")
    name = info.get("SessionName", "")
    print(f"{i:>2}  {str(vid):>5} {str(caps):>4} {tlen:>6}  {name}")
