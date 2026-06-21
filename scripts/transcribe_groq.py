"""Transcribe audio/video files to text via the Groq Whisper API.

For each audio/video file in --dir: extracts 16 kHz mono FLAC with ffmpeg (smaller
upload, better ASR accuracy), sends it to Groq's whisper-large-v3, and writes
<basename>.txt into the output folder (default: <dir>/transcripts).

Idempotent: skips a file whose transcript already exists and is non-empty (unless --force).
No local ML deps -- only ffmpeg + requests. Needs GROQ_API_KEY in .env (or env).

Usage:
  python transcribe_groq.py --dir "<folder>" [--out "<folder>"] [--model whisper-large-v3] [--force]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
AUDIO_EXT = {".webm", ".mp4", ".m4a", ".mp3", ".wav", ".mkv", ".mov", ".aac", ".ogg", ".flac"}


def numeric_key(p: Path):
    """Sort 'C3', 'C10' numerically; files without a C-number sort last by name."""
    m = re.match(r"^[Cc](\d+)", p.stem)
    return (0, int(m.group(1))) if m else (1, p.stem.lower())


MAX_UPLOAD = 24 * 1024 * 1024  # stay under Groq's 25 MB limit


def to_flac(src: Path, dst: Path) -> None:
    """Extract mono 16 kHz FLAC audio from any media file."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "flac", str(dst)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def flac_duration(flac: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(flac)],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def split_flac(flac: Path, out_dir: Path) -> list[Path]:
    """Split into time-based chunks each under the upload limit, via clean -ss/-t
    re-encodes (the segment muxer can emit malformed FLAC that Groq 502s on)."""
    size = flac.stat().st_size
    if size <= MAX_UPLOAD:
        return [flac]
    dur = flac_duration(flac)
    n = int(size // MAX_UPLOAD) + 1
    seg = (dur / n) if dur else 600.0
    chunks = []
    for i in range(n):
        start = i * seg
        dst = out_dir / f"{flac.stem}_{i:03d}.flac"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(start), "-t", str(seg + 1),
             "-i", str(flac), "-c:a", "flac", str(dst)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if dst.exists() and dst.stat().st_size > 1000:
            chunks.append(dst)
    return chunks


def transcribe(flac: Path, api_key: str, model: str, retries: int = 5) -> str:
    last = ""
    for attempt in range(retries):
        with open(flac, "rb") as fh:
            resp = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (flac.name, fh, "audio/flac")},
                data={"model": model, "response_format": "text", "temperature": "0"},
                timeout=300,
            )
        if resp.ok:
            return resp.text.strip()
        last = f"Groq API {resp.status_code}: {resp.text[:200]}"
        # Retry transient 429/5xx; fail fast on client errors (4xx)
        if resp.status_code not in (429, 500, 502, 503, 504):
            break
        wait = min(2 ** attempt, 20)
        print(f"    (retry {attempt + 1}/{retries} after {wait}s -- {resp.status_code})")
        time.sleep(wait)
    raise RuntimeError(last)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--model", default="whisper-large-v3")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        print("!! GROQ_API_KEY not set in .env -- add it and re-run.")
        raise SystemExit(1)

    src_dir = Path(args.dir)
    out_dir = Path(args.out) if args.out else src_dir / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(
        (p for p in src_dir.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXT),
        key=numeric_key,
    )
    if not files:
        print(f"No audio/video files in {src_dir}")
        return

    print(f"Transcribing {len(files)} file(s) via Groq '{args.model}'\n")
    for i, f in enumerate(files, 1):
        dest = out_dir / (f.stem + ".txt")
        if dest.exists() and dest.stat().st_size > 0 and not args.force:
            print(f"[{i}/{len(files)}] {f.name} -- exists, skipping")
            continue
        print(f"[{i}/{len(files)}] {f.name} -- extracting audio...")
        t0 = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            flac = Path(tmp) / (f.stem + ".flac")
            try:
                to_flac(f, flac)
            except subprocess.CalledProcessError:
                print("    !! ffmpeg failed -- skipping")
                continue
            mb = flac.stat().st_size / 1e6
            chunks = split_flac(flac, Path(tmp))
            label = f"{mb:.1f} MB FLAC" + (f" -> {len(chunks)} chunks" if len(chunks) > 1 else "")
            print(f"    -> {label}, sending to Groq...")
            try:
                pieces = [transcribe(c, api_key, args.model) for c in chunks]
            except Exception as exc:
                print(f"    !! transcription failed: {exc}")
                continue
            text = " ".join(p for p in pieces if p).strip()
        dest.write_text(text, encoding="utf-8")
        print(f"    done: {dest.name} ({len(text)} chars, {time.time()-t0:.0f}s)")

    print(f"\nDone. Transcripts in: {out_dir}")


if __name__ == "__main__":
    main()
