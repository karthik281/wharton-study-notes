---
name: build-module-notes
version: 1.0.0
description: Build a comprehensive Obsidian study note for one Wharton lecture/module from its transcripts + slides/case, with YAML frontmatter and [[wikilinks]] to Concepts. Use for "build notes for <module>", "generate the note for this module", "make study notes from these transcripts".
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - AskUserQuestion
---

## When to invoke this skill

Use when the user wants a **new** study note synthesized for a Wharton module/lecture from its source material — e.g. "build the notes for OIDD 6360 Module 6", "generate the note for this async module", "make study notes from these transcripts". For *adding to an existing note*, use **merge-notes** instead.

## What this produces

One Obsidian-ready `<Module Title>.md` inside the module folder: YAML frontmatter + `# Title` + MOC backlink + a thorough, faithful, study-note body (not a summary) that follows the lecture's arc, reconciles audio against slides/case, shows worked numbers, and links concepts with `[[wikilinks]]`.

**Preferred path — compose the existing script.** `scripts/build_module_notes.py` is a parameterized generator (generalized from `build_resource_notes.py`): give it `--folder/--title/--course/--course-short/--code/--session/--tags` and optional `--moc/--sibling`, and it gathers transcripts + slides/case, calls Claude, derives the `concepts:` frontmatter from the wikilinks used, and writes `<Title>.md` (refusing to overwrite). This is the "let Claude orchestrate, not regenerate boilerplate" path — prefer it. Run it (needs `ANTHROPIC_API_KEY` in `.env`):

```
& "C:\Users\raoka\Documents\Ideas\Agents\Wharton Study Notes\venv\Scripts\python.exe" "C:\Users\raoka\Documents\Ideas\Agents\Wharton Study Notes\scripts\build_module_notes.py" --folder "<module folder>" --title "<Title>" --course "<Course Folder>" --course-short "<Short>" --code "<CODE>" --session <n> --tags "<t1, t2>" --sibling "<optional>"
```

**Inline path — when the user wants you to do the synthesis yourself**, or to review/curate before writing, or when no API key is available. Then read the transcripts and slides/case directly and produce the same output. Either way, `scripts/build_module_notes.py` (and the originals `build_resource_notes.py` / `build_cash_notes.py`) are the source of truth for the `SYSTEM` prompt, frontmatter schema, and assembly order — read one before starting.

## Project conventions (must follow)

- **Output base:** `C:\Users\raoka\Documents\WEMBA\Term 4` (override env var `STUDY_NOTES_OUTPUT_DIR`). Standard course folders:
  - `FNCE 7310 - Global Valuation & Risk Analysis`
  - `OIDD 6360 - Scaling Operations`
  - `OIDD-MGMT 6910 & LGST 8060 - Negotiations`
- **Module folder layout:** transcripts in `<module>/transcripts/*.txt`; slide decks in `<module>/materials/*.pdf`; case files in a `<...> Case/` subfolder (`*.pdf`, `*.xlsx`, `*.html`). The note `.md` is written at the module-folder root.
- **Concepts live per course** in `<course folder>/Concepts/*.md`. The file *stems* are the exact `[[wikilink]]` targets.
- **PowerShell rule (from CLAUDE.md):** never `cd` then run; always use absolute paths. To run the build script:
  `& "C:\Users\raoka\Documents\Ideas\Agents\Wharton Study Notes\venv\Scripts\python.exe" "C:\Users\raoka\Documents\Ideas\Agents\Wharton Study Notes\scripts\build_resource_notes.py"`

## Steps

1. **Locate inputs.** Resolve the module folder. `Glob` `transcripts/*.txt` (sort numerically by `OR<n>` / `C<n>` prefix, else by name), `materials/*.pdf`, and any `* Case/*` files. List the `Concepts/*.md` stems for the course — these are your wikilink vocabulary. If anything ambiguous (which module, which course), ask with AskUserQuestion before generating.

2. **Read everything.** Read all transcripts in order. Read slides/case PDFs (use Read with `pages` for long PDFs). Transcripts are ASR — **the slides/case are the source of truth** for spellings, names, and exact figures.

3. **Synthesize the body** following the `SYSTEM` prompt in `build_resource_notes.py`:
   - Coverage: capture EVERY concept, definition, framework, model, case, example, number, rule, formula, and piece of advice. Length scales with richness — a 2–3h module yields a long, detailed note. Reproduce every enumerated list in full.
   - Correct ASR errors using the slides (e.g. "news vendor" → "Newsvendor", "blitz scaling" → "Blitzscaling"; fix company/person/financial-term spellings).
   - Reconcile numbers: where slides/case give exact figures/tables/capacities, use them. **Show worked calculations** (revenue per scenario, E[NPV], marginal value vs. cost, optimal capacities), in tables where structured.
   - **Wikilinks:** wrap mentions of existing concept names in `[[Exact Name]]` (match a `Concepts/` stem exactly); use `[[Name|display]]` when grammar needs it; you may introduce new `[[Wikilinks]]` for important concepts not yet in `Concepts/`. Link the first/most important mention, don't over-link.
   - **Headings:** start with `## Overview` (2–4 short paragraphs + core thesis), then thematic `##` sections following the lecture arc with rich `###` subsections and tables, then `## Frameworks & Models Summary`, `## Action Items / Takeaways` (numbered), `## Exam / Discussion Prep` (likely questions WITH full answers).
   - Diagrams: use Mermaid fenced blocks when a decision tree / flow / matrix aids understanding (renders natively in Obsidian).

4. **Assemble the file** exactly like the script does:
   - YAML frontmatter: `title`, `course`, `code`, `session`, `type: session-note`, `tags: [...]`, `concepts: [...]` (derive from the `[[wikilinks]]` you actually used, excluding MOC/sibling links), `materials: [...]` (the slide/case filenames).
   - Then `# <Title>`, then a backlink blockquote `> Part of [[<CODE> - MOC]] · ...`, then `---`, then the body.
   - Mirror the frontmatter `tags`/`code`/`course` style of the sibling note already in that course folder.

5. **Write** the note to `<module>/<Title>.md` with `Write`. Do not overwrite an existing note without confirming — if one exists, suggest **merge-notes** instead.

6. **Report** briefly: file path, section outline, how many concepts were linked, and any figures you had to reconcile between audio and slides.

## Gotchas (highest-signal — read these)

- **Transcripts are ASR (auto-captioned) and misspell technical terms.** The slides/case are the source of truth. Routinely fix: `news vendor → Newsvendor`, `blitz scaling → Blitzscaling`, plus company/person/financial-term spellings. Never propagate an ASR spelling into the note.
- **Transcript order is by `OR<n>` / `C<n>` prefix, numerically — not lexically.** A plain sort puts `OR10` before `OR2`. Use the numeric key (see `numeric_key` in the script) or the lecture arc breaks.
- **`[[wikilinks]]` must match a `Concepts/*.md` *stem* exactly** (case and spacing). A near-miss creates an orphan note in Obsidian. Use `[[Exact Name|display]]` when grammar needs a different surface form. Only introduce a *new* `[[wikilink]]` deliberately, for a genuinely new concept.
- **Reconcile numbers against the slides/case, and show the arithmetic.** Where audio and slides disagree on a figure, the slide/case wins. Recompute derived numbers yourself (e.g. CapEx, E[NPV]) rather than trusting a spoken figure — the professor sometimes misstates.
- **The note `.md` lives at the module-folder root**, not in `materials/` or `transcripts/`. Frontmatter `materials:` lists the slide/case *filenames* you actually used; `concepts:` is derived from the wikilinks you actually placed (exclude MOC/sibling links).
- **Never overwrite an existing `<Title>.md`.** If one exists, stop and route to **merge-notes** — the script already refuses to overwrite; do the same inline.
- **Mirror the sibling note already in that course folder** for frontmatter `tags`/`code`/`course` style and the backlink line, so the vault stays consistent.

## Quality bar

Faithful and complete over brief. Specific and analytical, never generic. Every number traceable to a transcript or slide. Every `[[wikilink]]` either matches a `Concepts/` stem or is a deliberate new concept. Beyond these guardrails, adapt freely to the module — the section arc should follow *this* lecture, not a fixed template.
