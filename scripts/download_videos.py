"""Download Panopto lecture videos (MP4) for the configured sessions.

For each session id in PANOPTO_SESSION_IDS, fetches DeliveryInfo to get the
pre-signed CloudFront podcast MP4 URL, maps the session to its local course/session
folder by course number + date, and streams the MP4 to <session>/materials/video.mp4.

Resumable: if a partial/complete file exists, resumes via HTTP Range. Skips files
that are already complete. Signed URLs are time-limited, so DeliveryInfo is fetched
immediately before each download.

Usage:
  python download_videos.py            # download all configured sessions
  python download_videos.py --limit 1  # download only the first (test run)
"""

import argparse
import logging
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("video_dl")

NOTES_ROOT = Path(r"C:\Users\raoka\Documents\WEMBA\Term 4")
SERVER = os.environ["PANOPTO_SERVER"].strip().rstrip("/")
COOKIE = os.environ.get("PANOPTO_COOKIE", "").strip()
SESSION_IDS = [s.strip() for s in os.environ.get("PANOPTO_SESSION_IDS", "").split(",") if s.strip()]

HEADERS = {"User-Agent": "Mozilla/5.0", "Cookie": COOKIE}
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
# Session folders: '<NN> <ddMonyy> - <Class Name>', e.g. '01 30Apr26 - Currency Markets'.
FOLDER_DATE_RE = re.compile(r"^\d+\s+(\d{2})([A-Za-z]{3})(\d{2})\b")
NAME_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")


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
    streams = delivery.get("PodcastStreams") or []
    for s in streams:
        u = s.get("StreamUrl")
        if u and ".mp4" in u:
            return u
    return None


def find_session_folder(session_name: str) -> Path | None:
    """Map a Panopto SessionName to its local session folder by course number + date."""
    # Course numbers (e.g. 6360, 7310, 6910) -- exclude the year (2026), which appears
    # in every course folder name and would defeat course disambiguation.
    nums = [n for n in re.findall(r"\b(\d{4})\b", session_name) if not 2000 <= int(n) <= 2099]
    dm = NAME_DATE_RE.search(session_name)                 # M/D
    if not nums or not dm:
        return None
    month, day = int(dm.group(1)), int(dm.group(2))

    for course_dir in NOTES_ROOT.iterdir():
        if not course_dir.is_dir():
            continue
        if not any(n in course_dir.name for n in nums):
            continue
        for sub in course_dir.iterdir():
            if not sub.is_dir():
                continue
            fm = FOLDER_DATE_RE.match(sub.name)
            if fm and (_MONTHS.get(fm.group(2).title(), 0), int(fm.group(1))) == (month, day):
                return sub
    return None


def download(url: str, dest: Path, force: bool = False) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Determine total size
    head = requests.get(url, headers={**HEADERS, "Range": "bytes=0-0"}, timeout=30, stream=True)
    head.raise_for_status()
    cr = head.headers.get("Content-Range", "")
    total = int(cr.split("/")[-1]) if "/" in cr else None
    head.close()

    existing = 0 if force else (dest.stat().st_size if dest.exists() else 0)
    if total and existing >= total:
        log.info("    already complete (%.2f GB) -- skipping", total / 1e9)
        return

    mode = "ab" if existing else "wb"
    headers = {**HEADERS}
    if existing:
        headers["Range"] = f"bytes={existing}-"
        log.info("    resuming at %.2f GB", existing / 1e9)

    with requests.get(url, headers=headers, timeout=60, stream=True) as r:
        r.raise_for_status()
        done = existing
        next_mark = done + 50 * 1024 * 1024
        with open(dest, mode) as f:
            for chunk in r.iter_content(1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if done >= next_mark:
                    pct = f"{100 * done / total:.0f}%" if total else "?"
                    log.info("    %.2f GB (%s)", done / 1e9, pct)
                    next_mark = done + 50 * 1024 * 1024
    log.info("    done: %s (%.2f GB)", dest, dest.stat().st_size / 1e9)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only download the first N sessions")
    ap.add_argument("--force", action="store_true", help="re-download even if a file already exists")
    ap.add_argument("--match", default=None, help="only sessions whose name contains this substring")
    args = ap.parse_args()

    ids = SESSION_IDS[: args.limit] if args.limit else SESSION_IDS
    log.info("Downloading %d of %d session(s)\n", len(ids), len(SESSION_IDS))

    ok = 0
    for i, sid in enumerate(ids, 1):
        try:
            d = delivery_info(sid)
            name = d.get("SessionName", sid)
            if args.match and args.match.lower() not in name.lower():
                continue
            log.info("[%d/%d] %s", i, len(ids), name)
            folder = find_session_folder(name)
            if folder is None:
                log.warning("    ! could not map to a local folder -- skipping")
                continue
            url = podcast_mp4_url(d)
            if not url:
                log.warning("    ! no podcast MP4 available -- skipping")
                continue
            dest = folder / "materials" / "video.mp4"
            download(url, dest, force=args.force)
            ok += 1
        except Exception as exc:
            log.error("    !! failed: %s", exc)

    log.info("\nFinished: %d/%d downloaded", ok, len(ids))


if __name__ == "__main__":
    main()
