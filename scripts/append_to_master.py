"""Append session note bodies to a course's "<CODE> - Master Notes.md".

The Master Notes file = a `## Contents` wikilink list + every session note's body
concatenated (YAML frontmatter and the `> Part of [[MOC]]` backlink line stripped),
separated by `---`. This appends one or more session notes to the end, idempotently
(skips any whose `# <Title>` H1 is already present).

It does NOT touch the `## Contents` list, the MOC, or the Dashboard — update those
session tables by hand (small edits). See the build-module-notes skill.

Usage:
  python append_to_master.py "<.../CODE - Master Notes.md>" "<.../NN ... .md>" ["<...>" ...]
"""
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def session_block(note_path: Path) -> tuple[str, str]:
    raw = note_path.read_text(encoding="utf-8")
    m = re.match(r"^---\n.*?\n---\n", raw, flags=re.DOTALL)  # strip YAML frontmatter
    rest = raw[m.end():] if m else raw
    lines = [ln for ln in rest.splitlines() if not ln.lstrip().startswith("> Part of")]
    body = "\n".join(lines).strip("\n")
    title = next((ln[2:].strip() for ln in lines if ln.startswith("# ")), note_path.stem)
    return title, body


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    master_path = Path(sys.argv[1])
    note_paths = [Path(p) for p in sys.argv[2:]]

    master = master_path.read_text(encoding="utf-8").rstrip("\n")
    added: list[str] = []
    for np in note_paths:
        title, body = session_block(np)
        if f"# {title}" in master:
            print(f"  already present, skipping: {title}")
            continue
        master += "\n\n---\n\n" + body
        added.append(title)
    master += "\n"
    if added:
        master_path.write_text(master, encoding="utf-8")
    print(f"{master_path.name}: appended {len(added)} -> {added}")


if __name__ == "__main__":
    main()
