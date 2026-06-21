"""Build one Obsidian study-notes .md for the Resource Constrained module.

Sibling of build_cash_notes.py. Inputs: all transcripts in <folder>/transcripts/*.txt
(OR1-OR10 async audio) + the Resource Constrained slides PDF + the Network Fleet case
PDF. Output: <folder>/Resource Constrained.md -- YAML frontmatter + MOC backlink +
structured notes with [[wikilinks]] to existing Concepts/ notes.

Uses Claude (Anthropic) for synthesis. Needs ANTHROPIC_API_KEY in .env.
"""
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

FOLDER = Path(r"C:\Users\raoka\Documents\WEMBA\Term 4\OIDD 6360 - Scaling Operations"
              r"\05 Async - Constrained\Resource Constrained")
CONCEPTS_DIR = Path(r"C:\Users\raoka\Documents\WEMBA\Term 4\OIDD 6360 - Scaling Operations\Concepts")
COURSE = "OIDD 6360 - Scaling Operations"
TITLE = "Resource Constrained"
MODEL = "claude-opus-4-8"


def numeric_key(p: Path):
    """Sort 'OR1', 'OR10' numerically; files without an OR-number sort last by name."""
    m = re.match(r"^(?:OR|[Cc])(\d+)", p.stem)
    return (0, int(m.group(1))) if m else (1, p.stem.lower())


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
  tables, or capacity numbers, use them. Show worked numerical calculations (revenue under
  each demand scenario, E[NPV], marginal value vs. marginal cost, optimal capacities).

Obsidian wikilinks (IMPORTANT):
- You are given a list of EXISTING concept-note names. Whenever you mention one of those
  concepts, wrap it in [[Exact Name]] wikilink syntax, matching the provided name EXACTLY.
- Use [[Name|display text]] when grammar needs a different surface form.
- You may also introduce [[Wikilinks]] for important concepts NOT in the list — Obsidian will
  create them later. Link the FIRST and most important mentions; don't over-link every occurrence.

Structure the note with these top-level headings (use ## ):
1. Overview — what this module covers and the core thesis (2-4 short paragraphs)
2. Then a sequence of thematic ## sections following the lecture's arc, with rich ### subsections,
   tables for any structured data (demand scenarios, capacity plans, utilization, marginal
   analysis), and worked numbers.
3. Frameworks & Models Summary
4. Action Items / Takeaways (numbered)
5. Exam / Discussion Prep (likely questions WITH full answers)

Do NOT write YAML frontmatter or a title heading — those are added separately. Start directly
with `## Overview`. Be specific and analytical, never generic. Prefer completeness over brevity."""


def main() -> None:
    tdir = FOLDER / "transcripts"
    tfiles = sorted((p for p in tdir.glob("*.txt") if p.stat().st_size > 0), key=numeric_key)
    if not tfiles:
        print("No transcripts found.")
        raise SystemExit(1)

    concept_names = sorted(p.stem for p in CONCEPTS_DIR.glob("*.md"))

    parts = [f"**Course:** {COURSE}", f"**Module:** {TITLE} (async — Module 5 Part II)", ""]
    parts.append("## Lecture Transcripts (in order)\n")
    for t in tfiles:
        parts.append(f"### Audio: {t.stem}\n{t.read_text(encoding='utf-8').strip()}\n")

    # Slides (in materials/) + Network Fleet case files (PDF case, model xlsx, calculator html)
    context_files = (
        sorted(FOLDER.glob("materials/*.pdf"))
        + sorted(FOLDER.glob("NetworkFleet Case/*.pdf"))
        + sorted(FOLDER.glob("NetworkFleet Case/*.xlsx"))
        + sorted(FOLDER.glob("NetworkFleet Case/*.html"))
    )
    for f in context_files:
        txt = extract_text(f)
        if txt:
            parts.append(f"## Slides/Case: {f.name}\n{txt[:80000]}\n")

    parts.append("## Existing concept-note names (use these for [[wikilinks]] when mentioned):\n"
                 + ", ".join(concept_names))

    user_content = "\n".join(parts)
    print(f"Transcripts: {len(tfiles)} | slides/case files: {len(context_files)} | concepts: {len(concept_names)} "
          f"| input ~{len(user_content)//4} tokens")

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    print(f"Generating notes with {MODEL}...")
    with client.messages.stream(
        model=MODEL,
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

    # Derive concepts list from the wikilinks actually used (for frontmatter)
    links = []
    for m in re.findall(r"\[\[([^\]]+)\]\]", body):
        name = m.split("|")[0].strip()
        if name and name not in ("OIDD 6360 - MOC", "05 Async - Constrained",
                                 "Cash Constrained") and name not in links:
            links.append(name)

    materials = list(dict.fromkeys(f.name for f in context_files))
    fm = (
        "---\n"
        f'title: "{TITLE}"\n'
        'course: "Scaling Operations"\n'
        'code: "OIDD 6360"\n'
        "session: 5\n"
        "type: session-note\n"
        "tags: [oidd-6360, async, constrained, resource-constraints, theory-of-constraints, "
        "newsvendor, operational-hedging, capacity-planning, forecasting-and-backcasting]\n"
        f"concepts: [{', '.join(links)}]\n"
        f"materials: [{', '.join(materials)}]\n"
        "---\n\n"
        f"# {TITLE}\n\n"
        "> Part of [[OIDD 6360 - MOC]] · sibling of [[05 Async - Constrained]] "
        "(Cash Constraints covered in [[Cash Constrained]])\n\n---\n\n"
    )
    out = FOLDER / f"{TITLE}.md"
    out.write_text(fm + body + "\n", encoding="utf-8")
    print(f"Wrote {out}  ({len(body)} chars, {len(links)} concepts linked)")


if __name__ == "__main__":
    main()
