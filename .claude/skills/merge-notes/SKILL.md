---
name: merge-notes
version: 1.0.0
description: Merge the user's raw/handwritten notes into an existing generated Wharton module note, adding only content not already present, verified against the source transcripts, in the note's own format. Use for "merge these notes", "add my notes to the <module> note", "I have notes for <module>, combine them".
allowed-tools:
  - Read
  - Edit
  - Glob
  - Grep
  - Bash
  - AskUserQuestion
---

## When to invoke this skill

Use when the user supplies their own notes (handwritten, typed, or pasted) for a module that **already has a generated study note**, and wants them combined — e.g. "merge these notes into the Resource Constrained note", "add my notes to the OIDD 6360 Module 5 note if not already there". For building a note from scratch, use **build-module-notes** instead.

## Core principle

**Additive and verified, never destructive.** The generated note is usually more complete and more detailed than the raw notes. Add only what is *genuinely missing*; verify anything new or uncertain against the source transcripts before writing it; never delete or overwrite existing content; flag discrepancies rather than silently "correcting" the note to match the raw notes.

## Project conventions

- Notes base: `C:\Users\raoka\Documents\WEMBA\Term 4` (override `STUDY_NOTES_OUTPUT_DIR`). Course folders: `FNCE 7310 - ...`, `OIDD 6360 - Scaling Operations`, `OIDD-MGMT 6910 & LGST 8060 - Negotiations`.
- The target note is the module's `<Title>.md` at the module-folder root. **Source transcripts** for verification live in `<module>/materials/transcript.txt` (ASR — treat slides/case as the spelling/number source of truth), alongside `materials/video.mp4` and the slide `materials/*.pdf`. (Legacy async modules may instead use a `transcripts/*.txt` subfolder.)
- Concepts vocabulary: `<course folder>/Concepts/*.md` stems are the exact `[[wikilink]]` targets.
- PowerShell rule (CLAUDE.md): never `cd` then run; use absolute paths.

## Steps

1. **Locate the target note.** From the module name the user gives, `Glob`/`Grep` under the output base to find the `<Title>.md`. If more than one plausible match, confirm with AskUserQuestion. `Read` the whole note so you know its structure, sections, tables, wikilink style, and what it already covers.

2. **Parse the raw notes into discrete items.** Break the user's notes into atomic claims/points (per heading/line/bullet). Keep the user's own section labels (e.g. "OR2", "OR4") as a map to where each belongs.

3. **Classify each item against the existing note:**
   - **Already present** (semantically, even if worded differently or more detailed) → skip. Do not duplicate.
   - **Genuinely missing** → candidate to add.
   - **Conflicting** (raw note's number/attribution differs from the note's) → do NOT overwrite; queue as a discrepancy to flag.
   - **Explicit instruction** (e.g. "prepare this decision tree and add it", "add a diagram") → treat as a required addition, not just a fact.

4. **Verify before adding.** For every candidate addition and every conflict, check the **source transcripts** (`Grep`/`Read` `transcripts/*.txt`, and slides if needed) to confirm wording, attribution, names, and figures. Prefer the transcript/slide truth over the raw note when they disagree. Do not add an unverifiable claim as fact — if it can't be confirmed, either omit it or add it clearly marked as the user's own annotation.

5. **Insert additions in place,** matching the note's existing conventions:
   - Put each addition in the section that matches its topic (use the user's OR#/section hints).
   - Match formatting: prose vs. tables vs. callouts (`>`), and reuse `[[wikilinks]]` for any concept that has a `Concepts/` stem (exact match) or is already linked elsewhere in the note.
   - For requested diagrams, use Mermaid fenced blocks (decision trees, flows, 2×2s) — they render in Obsidian.
   - Use `Edit` with tight, unique anchors. Preserve everything already there.

6. **Do not silently fix conflicts.** Leave the note's verified values as-is and surface the discrepancy to the user in your summary (e.g. "your notes say CapEx 11.625M; the note and the transcript math give 11.65M — kept 11.65M").

7. **Report (discussion summary)** at the end:
   - **Added** — each new item and which section it went to (and any diagram built).
   - **Already present** — confirm the bulk that was skipped, so the user sees nothing was lost.
   - **Discrepancies flagged** — raw-note figures/labels that disagree with the verified note, with what you kept and why.

## Gotchas (highest-signal — read these)

- **The raw notes are usually a *subset* of the generated note, often less accurate.** Default assumption: most items are already covered, frequently in more detail. Your job is to find the few genuine gaps, not to re-add what's there. Resist the urge to "improve" passages that are already correct.
- **Raw-note numbers are frequently slips — verify, don't import.** Real examples from this vault: handwritten "CapEx 11.625M" vs. the correct **$11.65M** (= 4 + 45×0.03 + 35×0.02 + 70×0.08); Tesla labeled "excess inventory" when it's the **excess-capacity** corner of the triangle. Recompute against the transcript/slides and **keep the verified value**, flagging the conflict — never overwrite the note to match the slip.
- **"Semantically present" ≠ "worded identically."** Before adding, check whether the idea already appears under a different heading or phrasing (e.g. the user's "OR9 modeling risk 2×2" is the note's "Risk-Based Forecasting 5 steps"). Skip true duplicates even when the wording differs.
- **Source transcripts are ASR — confirm attributions/spellings there before adding.** A vague raw note like "McKinsey says something about flexibility" must be checked against `transcripts/*.txt`: confirm it's *McKinsey Quarterly on evaluating flexible assets*, not conflated with the Upton flexibility definition already in the note. Add the verified version, not the vague one.
- **Honor explicit build instructions as required additions.** "Prepare this decision tree and add it" means actually construct the Mermaid diagram and insert it — not just note that a tree belongs there.
- **`[[wikilinks]]` in additions must match a `Concepts/*.md` stem exactly,** and reuse links already present in the note for the same concept. Don't introduce a near-miss variant that orphans in Obsidian.
- **Map the user's section labels (OR#, C#) to the note's `##` sections** so each addition lands in the right place; the note follows the lecture arc, the raw notes follow the video order — they usually align but confirm.

## Guardrails

- Never delete or rewrite existing passages to "make room" — only insert.
- Never trust a raw-note number over a transcript/slide without saying so.
- If the user asks for a diagram or worked artifact, actually build it, don't just reference it.
- Keep the note's voice and structure; additions should read like the surrounding text.
- These are boundaries, not a script — adapt the order of steps to the notes in front of you.
