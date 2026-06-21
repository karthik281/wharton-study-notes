"""Read-only probe: verify cookie validity and inspect the GetSessions response.

Dumps: total session count, the full key set of one raw result, and a sample of
(SessionName, StartTime, FolderName) so we can confirm date-range filtering is feasible.
"""
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

SERVER = os.environ["PANOPTO_SERVER"].strip().rstrip("/")
COOKIE = os.environ.get("PANOPTO_COOKIE", "").strip()

url = f"https://{SERVER}/Panopto/Services/Data.svc/GetSessions"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"https://{SERVER}/Panopto/Pages/Sessions/List.aspx",
    "Content-Type": "application/json",
    "Cookie": COOKIE,
}
body = {
    "queryParameters": {
        "query": "",
        "sortColumn": 1,
        "sortAscending": False,
        "maxResults": 10,
        "startIndex": 0,
        "folderID": None,
        "bookmarked": False,
        "sessionListOnly": True,
        "getFolderData": True,
        "isSharedFolderSearch": False,
    }
}

resp = requests.post(url, headers=headers, json=body, timeout=30)
print("HTTP status:", resp.status_code)
ctype = resp.headers.get("content-type", "")
print("content-type:", ctype)
if "json" not in ctype:
    print("\n!! Not JSON -- cookie likely EXPIRED. First 300 chars of body:")
    print(resp.text[:300])
    raise SystemExit(1)

data = resp.json()
d = data.get("d", {})
results = d.get("Results", [])
print("TotalNumber:", d.get("TotalNumber"))
print("Results on this page:", len(results))
if results:
    print("\n=== raw keys of first result ===")
    print(sorted(results[0].keys()))
    print("\n=== sample sessions (name | StartTime | folder) ===")
    for r in results:
        print(f"  {r.get('SessionName')!r:60} | {r.get('StartTime')!r} | {r.get('FolderName')!r}")
