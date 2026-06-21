"""Transcribe audio/video files in a folder to plain-text transcripts using faster-whisper.

Writes one <basename>.txt per source file into an output folder (default: <dir>/transcripts).
Idempotent: skips a file if its transcript already exists and is non-empty (unless --force).

Usage:
  python transcribe_audio.py --dir "<folder>" [--out "<folder>"] [--model small.en] [--force]
"""
import argparse
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

AUDIO_EXT = {".webm", ".mp4", ".m4a", ".mp3", ".wav", ".mkv", ".mov", ".aac", ".ogg", ".flac"}


def numeric_key(p: Path):
    """Sort 'C3', 'C10' numerically; files without a C-number sort last by name."""
    m = re.match(r"^[Cc](\d+)", p.stem)
    return (0, int(m.group(1))) if m else (1, p.stem.lower())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--model", default="small.en")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

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

    print(f"Found {len(files)} file(s). Loading faster-whisper model '{args.model}' (CPU/int8)...")
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    print("Model loaded.\n")

    for i, f in enumerate(files, 1):
        dest = out_dir / (f.stem + ".txt")
        if dest.exists() and dest.stat().st_size > 0 and not args.force:
            print(f"[{i}/{len(files)}] {f.name} -- transcript exists, skipping")
            continue
        print(f"[{i}/{len(files)}] {f.name} -- transcribing...")
        t0 = time.time()
        segments, info = model.transcribe(str(f), beam_size=5, vad_filter=True)
        parts = []
        for seg in segments:
            txt = seg.text.strip()
            if txt:
                parts.append(txt)
        text = " ".join(parts).strip()
        dest.write_text(text, encoding="utf-8")
        dur = getattr(info, "duration", 0) or 0
        print(f"    -> {dest.name}  ({len(text)} chars, audio {dur/60:.1f} min, "
              f"took {time.time()-t0:.0f}s)")

    print(f"\nDone. Transcripts in: {out_dir}")


if __name__ == "__main__":
    main()
