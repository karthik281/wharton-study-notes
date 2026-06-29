"""Build one Obsidian study-notes .md for ANY module (parameterized).

Generalized from build_resource_notes.py / build_cash_notes.py so the
/build-module-notes skill can compose it instead of regenerating boilerplate.

Inputs: all transcripts in <folder>/transcripts/*.txt + any slide PDFs in
<folder>/materials/*.pdf + any case files (*.pdf/*.xlsx/*.html) in case
subfolders. Output: <folder>/<Title>.md -- YAML frontmatter + MOC backlink +
structured notes with [[wikilinks]] to existing Concepts/ notes.

Uses Claude (Anthropic) for synthesis. Needs ANTHROPIC_API_KEY in .env.

Example:
  python scripts/build_module_notes.py \
    --folder "C:/.../OIDD 6360 - Scaling Operations/06 Async - X/Topic" \
    --title "Topic Name" \
    --course "OIDD 6360 - Scaling Operations" \
    --course-short "Scaling Operations" \
    --code "OIDD 6360" --session 6 \
    --tags "oidd-6360, async, capacity-planning" \
    --sibling "05 Async - Constrained"
"""
import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
load_dotenv(PROJECT_DIR / ".env")

from file_processor import extract_text  # noqa: E402
import anthropic  # noqa: E402

DEFAULT_MODEL = "claude-opus-4-8"

SYSTEM = """You are an expert study-notes writer for a Wharton MBA student using Obsidian.

You are given the FULL audio transcripts of an asynchronous lecture module plus the
module's slide deck and the associated case. Produce comprehensive, faithful study notes
in Markdown — study notes, not a summary: capture everything of substance so the student
never has to re-watch the videos.

Coverage requirements:
- Capture EVERY concept, definition, framework, model, case, example, numerical detail,
  rule, formula, and piece of advice the professor presents. Length scales with richness.
- Reproduce every enumerated list ("there are three types of...") in full, each item explained.
- Preserve specific terminology, numbers, named cases, and named people. The transcripts are
  auto-generated (ASR) and may misspell technical terms — correct them using the slides as the
  source of truth (e.g. "news vendor" -> "Newsvendor", "blitz scaling" -> "Blitzscaling",
  company/person names, financial terms).
- Reconcile the audio with the slides and case: where the slides/case give exact figures,
  tables, or capacity numbers, use them. Show worked numerical calculations.

Obsidian wikilinks (IMPORTANT):
- You are given a list of EXISTING concept-note names. Whenever you mention one of those
  concepts, wrap it in [[Exact Name]] wikilink syntax, matching the provided name EXACTLY.
- Use [[Name|display text]] when grammar needs a different surface form.
- You may also introduce [[Wikilinks]] for important concepts NOT in the list — Obsidian will
  create them later. Link the FIRST and most important mentions; don't over-link every occurrence.

Structure the note with these top-level headings (use ## ):
1. Overview — what this module covers and the core thesis (2-4 short paragraphs)
2. Then a sequence of thematic ## sections following the lecture's arc, with rich ### subsections,
   tables for any structured data, and worked numbers. Use Mermaid fenced blocks for decision
   trees / flows / 2x2 matrices where a diagram aids understanding.
3. Frameworks & Models Summary
4. Action Items / Takeaways (numbered)
5. Exam / Discussion Prep (likely questions WITH full answers)

Do NOT write YAML frontmatter or a title heading — those are added separately. Start directly
with `## Overview`. Be specific and analytical, never generic. Prefer completeness over brevity."""


def numeric_key(p: Path):
    """Sort 'OR1', 'OR10', 'C3' numerically; files without that prefix sort last by name."""
    m = re.match(r"^(?:OR|[Cc])(\d+)", p.stem)
    return (0, int(m.group(1))) if m else (1, p.stem.lower())


def gather_context_files(folder: Path) -> list[Path]:
    """Slide decks in materials/ plus case files in any subfolder (excluding transcripts)."""
    files: list[Path] = sorted(folder.glob("materials/*.pdf"))
    for ext in ("*.pdf", "*.xlsx", "*.html"):
        for f in sorted(folder.glob(f"*/{ext}")):
            if f.parent.name.lower() not in ("materials", "transcripts") and f not in files:
                files.append(f)
    return files


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build an Obsidian module note from transcripts + slides/case.")
    ap.add_argument("--folder", required=True, help="Module folder (contains transcripts/, materials/).")
    ap.add_argument("--title", required=True, help="Note title, e.g. 'Resource Constrained'.")
    ap.add_argument("--course", required=True, help="Course folder name, e.g. 'OIDD 6360 - Scaling Operations'.")
    ap.add_argument("--course-short", required=True, help="Value for frontmatter 'course:', e.g. 'Scaling Operations'.")
    ap.add_argument("--code", required=True, help="Course code, e.g. 'OIDD 6360'.")
    ap.add_argument("--session", type=int, default=0, help="Session number for frontmatter.")
    ap.add_argument("--tags", default="", help="Comma-separated frontmatter tags.")
    ap.add_argument("--concepts-dir", default="", help="Override Concepts dir (default: <course>/Concepts).")
    ap.add_argument("--moc", default="", help="MOC note name (default: '<code> - MOC').")
    ap.add_argument("--sibling", default="", help="Optional sibling note name for the backlink line.")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    return ap.parse_args()


def main() -> None:
    a = parse_args()
    folder = Path(a.folder)
    course_dir = folder
    while course_dir.name != a.course and course_dir.parent != course_dir:
        course_dir = course_dir.parent
    concepts_dir = Path(a.concepts_dir) if a.concepts_dir else course_dir / "Concepts"
    moc = a.moc or f"{a.code} - MOC"

    # Transcripts live in materials/ (project convention: video.mp4 + transcript.txt
    # + slides all in materials/). Legacy async modules use a transcripts/ subfolder,
    # so accept both.
    tfiles = sorted(
        (p for d in (folder / "materials", folder / "transcripts")
         for p in d.glob("*.txt") if p.stat().st_size > 0),
        key=numeric_key,
    )
    if not tfiles:
        print(f"No transcripts found in {folder / 'materials'} or {folder / 'transcripts'}")
        raise SystemExit(1)

    concept_names = sorted(p.stem for p in concepts_dir.glob("*.md")) if concepts_dir.exists() else []

    parts = [f"**Course:** {a.course}", f"**Module:** {a.title}", ""]
    parts.append("## Lecture Transcripts (in order)\n")
    for t in tfiles:
        parts.append(f"### Audio: {t.stem}\n{t.read_text(encoding='utf-8').strip()}\n")

    context_files = gather_context_files(folder)
    for f in context_files:
        txt = extract_text(f)
        if txt:
            parts.append(f"## Slides/Case: {f.name}\n{txt[:80000]}\n")

    if concept_names:
        parts.append("## Existing concept-note names (use these for [[wikilinks]] when mentioned):\n"
                     + ", ".join(concept_names))

    user_content = "\n".join(parts)
    print(f"Transcripts: {len(tfiles)} | slides/case files: {len(context_files)} | "
          f"concepts: {len(concept_names)} | input ~{len(user_content)//4} tokens")

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    print(f"Generating notes with {a.model}...")
    with client.messages.stream(
        model=a.model,
        max_tokens=32000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        msg = stream.get_final_message()
    body = next((b.text for b in msg.content if b.type == "text"), "").strip()
    if not body:
        print("!! empty generation")
        raise SystemExit(1)

    # Derive frontmatter `concepts` from the wikilinks actually used.
    skip = {moc, a.sibling, a.title}
    links: list[str] = []
    for m in re.findall(r"\[\[([^\]]+)\]\]", body):
        name = m.split("|")[0].strip()
        if name and name not in skip and name not in links:
            links.append(name)

    materials = list(dict.fromkeys(f.name for f in context_files))
    backlink = f"> Part of [[{moc}]]"
    if a.sibling:
        backlink += f" · sibling of [[{a.sibling}]]"
    fm = (
        "---\n"
        f'title: "{a.title}"\n'
        f'course: "{a.course_short}"\n'
        f'code: "{a.code}"\n'
        f"session: {a.session}\n"
        "type: session-note\n"
        f"tags: [{a.tags}]\n"
        f"concepts: [{', '.join(links)}]\n"
        f"materials: [{', '.join(materials)}]\n"
        "---\n\n"
        f"# {a.title}\n\n"
        f"{backlink}\n\n---\n\n"
    )
    out = folder / f"{a.title}.md"
    if out.exists():
        print(f"!! {out} already exists -- refusing to overwrite. Use merge-notes instead.")
        raise SystemExit(1)
    out.write_text(fm + body + "\n", encoding="utf-8")
    print(f"Wrote {out}  ({len(body)} chars, {len(links)} concepts linked)")


if __name__ == "__main__":
    main()
