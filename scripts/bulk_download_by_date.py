"""Download every Panopto video whose recording StartTime falls in a date range.

Pages through all sessions (Data.svc GetSessions, newest-first), filters by
StartTime, and for each match fetches the pre-signed podcast MP4 and streams it
to a flat destination folder. Resumable; signed URLs fetched immediately before
each download.

Usage:
  python bulk_download_by_date.py --start 2020-04-24 --end 2024-04-26 --dest "C:\\path" --dry-run
  python bulk_download_by_date.py --start 2020-04-24 --end 2024-04-26 --dest "C:\\path"
"""
import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# Console may be cp1252; session titles contain non-ASCII. Don't let printing crash.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

SERVER = os.environ["PANOPTO_SERVER"].strip().rstrip("/")
COOKIE = os.environ.get("PANOPTO_COOKIE", "").strip()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Cookie": COOKIE,
}
JSON_HEADERS = {
    **HEADERS,
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"https://{SERVER}/Panopto/Pages/Sessions/List.aspx",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
_DATE_RE = re.compile(r"/Date\((\d+)")


def parse_start_time(s: str) -> dt.datetime | None:
    m = _DATE_RE.search(s or "")
    if not m:
        return None
    return dt.datetime.fromtimestamp(int(m.group(1)) / 1000, tz=dt.timezone.utc)


def enumerate_sessions():
    """Yield every raw session dict (newest-first).

    NOTE: this Data.svc endpoint ignores ``startIndex`` (every page returns the
    same newest slice), but it DOES honor ``maxResults`` -- so we request a count
    larger than the library and get the whole list in one call. We bump the ask
    until the returned count stops growing, in case the library exceeds the cap.
    """
    url = f"https://{SERVER}/Panopto/Services/Data.svc/GetSessions"
    seen = set()
    ask = 1000
    last_returned = -1
    while True:
        body = {"queryParameters": {
            "query": "", "sortColumn": 1, "sortAscending": False,
            "maxResults": ask, "startIndex": 0, "folderID": None,
            "bookmarked": False, "sessionListOnly": True, "getFolderData": True,
            "isSharedFolderSearch": False,
        }}
        resp = requests.post(url, headers=JSON_HEADERS, json=body, timeout=120)
        resp.raise_for_status()
        if "json" not in resp.headers.get("content-type", ""):
            raise RuntimeError("GetSessions did not return JSON -- cookie expired")
        d = resp.json().get("d", {})
        results = d.get("Results", []) or []
        total = d.get("TotalNumber", 0)
        if len(results) <= last_returned:
            # not growing -- give up bumping
            pass
        last_returned = len(results)
        if len(results) >= total or ask >= 5000:
            for r in results:
                sid = r.get("DeliveryID") or r.get("SessionID")
                if sid and sid not in seen:
                    seen.add(sid)
                    yield r
            return
        ask *= 2


def delivery_info(session_id: str) -> dict:
    url = (
        f"https://{SERVER}/Panopto/Pages/Viewer/DeliveryInfo.aspx"
        f"?deliveryId={session_id}&invocationId=&isLiveNotes=false&refreshAuthCookie=true"
        f"&isActiveBroadcast=false&isEditing=false&isKollectiveAgentInstalled=false"
        f"&isEmbed=false&responseType=json"
    )
    resp = requests.get(url, headers={**HEADERS, "Accept": "application/json"}, timeout=30)
    resp.raise_for_status()
    if "json" not in resp.headers.get("content-type", ""):
        raise RuntimeError("DeliveryInfo did not return JSON -- cookie likely expired")
    return resp.json().get("Delivery", {})


def podcast_mp4_url(delivery: dict) -> str | None:
    for s in delivery.get("PodcastStreams") or []:
        u = s.get("StreamUrl")
        if u and ".mp4" in u:
            return u
    return None


def safe_name(name: str, limit: int = 80) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name or "session").strip()
    name = re.sub(r"\s+", " ", name)
    return name[:limit].rstrip(" ._")


def download(url: str, dest: Path, force: bool = False) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    head = requests.get(url, headers={**HEADERS, "Range": "bytes=0-0"}, timeout=30, stream=True)
    head.raise_for_status()
    cr = head.headers.get("Content-Range", "")
    total = int(cr.split("/")[-1]) if "/" in cr else None
    head.close()
    existing = 0 if force else (dest.stat().st_size if dest.exists() else 0)
    if total and existing >= total:
        print(f"    already complete ({total/1e9:.2f} GB) -- skipping")
        return
    mode = "ab" if existing else "wb"
    h = {**HEADERS}
    if existing:
        h["Range"] = f"bytes={existing}-"
        print(f"    resuming at {existing/1e9:.2f} GB")
    with requests.get(url, headers=h, timeout=60, stream=True) as r:
        r.raise_for_status()
        done = existing
        mark = done + 100 * 1024 * 1024
        with open(dest, mode) as f:
            for chunk in r.iter_content(1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if done >= mark:
                    pct = f"{100*done/total:.0f}%" if total else "?"
                    print(f"    {done/1e9:.2f} GB ({pct})")
                    mark = done + 100 * 1024 * 1024
    print(f"    done -> {dest.name} ({dest.stat().st_size/1e9:.2f} GB)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD inclusive")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD inclusive")
    ap.add_argument("--dest", required=True, help="destination folder")
    ap.add_argument("--dry-run", action="store_true", help="list matches, do not download")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    start = dt.datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    end = dt.datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc) + dt.timedelta(days=1)
    if start > end:
        start, end = end - dt.timedelta(days=1), start + dt.timedelta(days=1)
    dest = Path(args.dest)

    print(f"Range (UTC): {start.date()} .. {(end - dt.timedelta(days=1)).date()} inclusive")
    print("Scanning library...\n")

    matches = []
    scanned = 0
    for r in enumerate_sessions():
        scanned += 1
        ts = parse_start_time(r.get("StartTime", ""))
        if ts is None:
            continue
        if start <= ts < end:
            matches.append((ts, r))
    matches.sort(key=lambda x: x[0])

    print(f"Scanned {scanned} sessions. {len(matches)} fall in range.\n")
    total_dur = 0.0
    n_avail = 0
    for ts, r in matches:
        dur = r.get("Duration") or 0
        total_dur += dur
        avail = r.get("IsDownloadAvailable", True)
        n_avail += 1 if avail else 0
        dl = "" if avail else "  [download flagged unavailable]"
        print(f"  {ts.date()}  {int(dur//60):>4}m  {r.get('SessionName')!r}{dl}")
    print(f"\nTotal: {len(matches)} videos, ~{total_dur/3600:.1f} hours of footage")
    print(f"Download-available: {n_avail} / {len(matches)}  "
          f"({len(matches) - n_avail} flagged unavailable)")

    if args.dry_run:
        print("\n(dry run -- nothing downloaded)")
        return
    if not matches:
        print("\nNothing to download.")
        return

    print(f"\nDownloading to: {dest}\n")
    ok = 0
    for i, (ts, r) in enumerate(matches, 1):
        sid = r.get("DeliveryID") or r.get("SessionID")
        name = r.get("SessionName", sid)
        print(f"[{i}/{len(matches)}] {ts.date()}  {name}")
        try:
            d = delivery_info(sid)
            url = podcast_mp4_url(d)
            if not url:
                print("    ! no podcast MP4 -- skipping")
                continue
            fname = f"{ts.date()} - {safe_name(name)} - {sid[:8]}.mp4"
            download(url, dest / fname, force=args.force)
            ok += 1
        except Exception as exc:
            print(f"    !! failed: {exc}")
    print(f"\nFinished: {ok}/{len(matches)} downloaded -> {dest}")


if __name__ == "__main__":
    main()
