"""Build comprehensive Obsidian-style study notes from all course material.

Per-course pipeline (--course "<course folder name>"):
  1. Map course-level resources (readings/cases/exams/prep plans) to the relevant session.
  2. Generate one comprehensive session note per session (transcript + slides + mapped resources).
  3. Generate one concept note per unique concept (per-course Concepts/ folder).
  4. Compile a course MOC (index + synthesis) and a Master document (merged session notes).

Single-session test:  --one "<absolute session folder path>"
"""
import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
import anthropic
import httpx

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from file_processor import extract_text, SUPPORTED_EXTENSIONS  # noqa: E402

NOTES_ROOT = Path(r"C:\Users\raoka\Documents\WEMBA\Term 4")
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 32000

# Retry/backoff for transient API/network failures (e.g. connection dropped
# mid-stream: httpx.ReadError [WinError 10054], 429s, 5xx, overloaded).
# Permanent errors (400 bad request, 401/403 auth, low-credit) are NOT retried.
MAX_ATTEMPTS = 5
BASE_DELAY = 2.0      # seconds; exponential: 2, 4, 8, 16 (+ jitter)
MAX_DELAY = 30.0
_RETRYABLE = (
    anthropic.APIConnectionError,   # includes APITimeoutError
    anthropic.RateLimitError,       # 429
    anthropic.InternalServerError,  # 5xx
    httpx.HTTPError,                # transport-level (ReadError, ConnectError, ...)
)
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
SESSION_RE = re.compile(r"^\d+\s")   # a numbered session folder (live, async, or slides-only)

SESSION_SYS = """You are an expert study-notes writer for a Wharton MBA student, producing notes for an Obsidian vault.

You are given ALL material for ONE class session: the lecture transcript (primary source), the lecture slides, and any readings/assignments/cases mapped to this session. Produce ONE comprehensive Markdown study note.

Output EXACTLY: YAML frontmatter, then the Markdown body. Nothing else.

Frontmatter keys:
---
title: "<the session title you are given>"
course: "<course full name>"
code: "<course code>"
session: <session number as an integer>
date: <YYYY-MM-DD>
type: session-note
tags: [<course-code-as-kebab>, session, <3-6 topical kebab-case tags>]
concepts: [<every key concept you wikilink in the body, exact Title Case names>]
materials: [<the source filenames you used>]
---

Body requirements:
- BE EXHAUSTIVE. Capture every concept, definition, framework, model, derivation, numerical example, case detail, rule, and piece of advice. There is NO length limit — write a long, complete note when the source is rich. Never compress or omit to save space.
- Lead with the transcript. Use slides for structure, exact figures/exhibits, and anything not spoken. Use readings/cases/assignments to deepen and cross-reference.
- Preserve the professor's exact terminology, examples, and numbers; quote memorable lines.
- Reproduce full enumerations/typologies — every item, each explained with its example.
- Link key concepts inline as [[Concept Name]] wikilinks, canonical Title Case, reused consistently. Every wikilinked concept must also appear in frontmatter `concepts`.
- Put a navigation line right after the H1: `> Part of [[<course code> - MOC]]`.

Begin the body with `# <session title>` then use sections such as: Overview, Key Concepts, Frameworks & Models, Worked Examples & Derivations, Case Studies, Slides — Notable Points, Readings & Assignments, Action Items / Takeaways, Exam / Discussion Prep.

Be specific and analytical, never generic. Output ONLY the note."""


# --------------------------------------------------------------------------- helpers
def parse_course(folder_name: str) -> tuple[str, str]:
    code, _, name = folder_name.partition(" - ")
    return code.strip(), name.strip()


def parse_session(folder_name: str) -> tuple[int, str, str]:
    m = re.match(r"^(\d+)\s+(\d{2})([A-Za-z]{3})(\d{2})\s*-\s*(.*)$", folder_name)
    if not m:
        m2 = re.match(r"^(\d+)\s+(.*)$", folder_name)
        return (int(m2.group(1)) if m2 else 0, "", folder_name)
    num, dd, mon, yy, cls = m.groups()
    return int(num), f"20{yy}-{_MONTHS.get(mon.title(), 1):02d}-{int(dd):02d}", cls.strip()


def is_session_folder(d: Path) -> bool:
    return d.is_dir() and bool(SESSION_RE.match(d.name))


def session_folders(course_dir: Path) -> list[Path]:
    """Numbered top-level session folders, plus nested async lectures (Async Modules/Lecture X)."""
    sessions = sorted([d for d in course_dir.iterdir() if is_session_folder(d)],
                      key=lambda d: parse_session(d.name)[0])
    async_root = course_dir / "Async Modules"
    if async_root.is_dir():
        sessions += sorted([d for d in async_root.iterdir()
                            if d.is_dir() and (d / "materials").exists()], key=lambda d: d.name)
    return sessions


def client_factory():
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def stream_completion(client, system: str, user: str, max_tokens: int = MAX_TOKENS) -> tuple[str, str]:
    """Stream a completion, retrying transient failures with exponential backoff.

    A dropped connection mid-stream discards the partial text and the whole call
    is retried (callers only write the note after this returns), so a network
    blip self-heals instead of failing the entire course build.
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with client.messages.stream(
                model=MODEL, max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
            ) as stream:
                text = "".join(stream.text_stream)
                final = stream.get_final_message()
            return text, final.stop_reason
        except _RETRYABLE as e:
            last_exc = e
        except anthropic.APIStatusError as e:
            # 4xx (bad request, auth, low-credit) won't self-heal — fail fast.
            if e.status_code < 500 and e.status_code not in (429, 529):
                raise
            last_exc = e
        if attempt < MAX_ATTEMPTS:
            delay = min(MAX_DELAY, BASE_DELAY * 2 ** (attempt - 1)) + random.uniform(0, 1)
            print(f"    ! transient API error ({type(last_exc).__name__}: {last_exc}); "
                  f"retry {attempt}/{MAX_ATTEMPTS - 1} in {delay:.1f}s")
            time.sleep(delay)
    raise last_exc  # exhausted retries


def gather_session_materials(session_dir: Path) -> tuple[str, list[dict]]:
    transcript, materials = "", []
    for p in sorted(session_dir.rglob("*")):
        if not p.is_file() or p.name == "video.mp4" or p.suffix.lower() == ".md":
            continue
        if p.name == "transcript.txt":
            transcript = p.read_text(encoding="utf-8", errors="ignore")
            continue
        if p.suffix.lower() in SUPPORTED_EXTENSIONS:
            t = extract_text(p)
            if t.strip():
                materials.append({"name": p.name, "text": t})
    return transcript, materials


def frontmatter_field(md: str, field: str) -> str:
    m = re.search(rf"^{field}:\s*(.+)$", md, re.M)
    return m.group(1).strip() if m else ""


def parse_concepts(md: str) -> list[str]:
    raw = frontmatter_field(md, "concepts")
    raw = raw.strip().lstrip("[").rstrip("]")
    return [c.strip().strip('"') for c in raw.split(",") if c.strip()]


def split_frontmatter(md: str) -> tuple[str, str]:
    m = re.match(r"^---\n.*?\n---\n", md, re.S)
    return (md[:m.end()], md[m.end():]) if m else ("", md)


# --------------------------------------------------------------------------- resources
def list_course_resources(course_dir: Path) -> list[Path]:
    """Supported files that are NOT inside a session folder (course-level resources)."""
    out = []
    for p in course_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        rel_top = p.relative_to(course_dir).parts[0]
        top = course_dir / rel_top
        if top.is_dir() and is_session_folder(top):
            continue  # belongs to a session
        if top.is_dir() and rel_top == "Async Modules":
            continue  # async sessions handled as sessions
        out.append(p)
    return out


def map_resources(course_dir: Path, client) -> dict[str, list[str]]:
    cache = course_dir / ".resource_map.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    sessions = [d.name for d in session_folders(course_dir)]
    resources = list_course_resources(course_dir)
    syllabus_txt = ""
    for p in resources:
        if "syllab" in p.name.lower():
            syllabus_txt = extract_text(p)[:30000]
            break
    rel_paths = [str(p.relative_to(course_dir)) for p in resources]
    user = (
        f"Course: {course_dir.name}\n\nSESSIONS (in order):\n" +
        "\n".join(f"- {s}" for s in sessions) +
        "\n\nRESOURCE FILES (course-level, not yet tied to a session):\n" +
        "\n".join(f"- {r}" for r in rel_paths) +
        (f"\n\nSYLLABUS (for mapping):\n{syllabus_txt}" if syllabus_txt else "") +
        "\n\nMap each resource file to the single session it best supports (by topic/date/"
        "syllabus). If a resource is general to the whole course (syllabus, overview, exam), "
        'assign it to "course". Output ONLY JSON: an object whose keys are the exact session '
        'folder names (or "course") and whose values are arrays of the exact resource file '
        "paths listed above. Every resource path must appear exactly once."
    )
    text, _ = stream_completion(client, "You map course resources to sessions. Output only JSON.",
                                user, max_tokens=4000)
    m = re.search(r"\{.*\}", text, re.S)
    mapping = json.loads(m.group(0)) if m else {}
    cache.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    print(f"  resource map: {sum(len(v) for v in mapping.values())} files across {len(mapping)} buckets")
    return mapping


# --------------------------------------------------------------------------- session notes
def generate_session_note(course_dir: Path, session_dir: Path, extra: list[Path], client) -> Path | None:
    code, name = parse_course(course_dir.name)
    num, date, cls = parse_session(session_dir.name)
    transcript, materials = gather_session_materials(session_dir)
    for p in extra:
        if p.exists():
            t = extract_text(p)
            if t.strip():
                materials.append({"name": p.name, "text": t})
    if not transcript.strip() and not materials:
        print(f"  ! no material in {session_dir.name} -- skipping")
        return None

    parts = [f"COURSE: {name}", f"COURSE CODE: {code}", f"SESSION NUMBER: {num}",
             f"DATE: {date}", f"SESSION TITLE: {session_dir.name}", ""]
    if transcript.strip():
        parts += ["## LECTURE TRANSCRIPT", transcript, ""]
    else:
        parts += ["## LECTURE TRANSCRIPT", "(none — no recording; base the note on the "
                  "slides and materials below)", ""]
    for mt in materials:
        parts += [f"## MATERIAL: {mt['name']}", mt["text"], ""]

    print(f"  [{session_dir.name}] transcript {len(transcript)} + {len(materials)} files")
    note, stop = stream_completion(client, SESSION_SYS, "\n".join(parts))
    out = session_dir / f"{session_dir.name}.md"
    out.write_text(note, encoding="utf-8")
    print(f"    -> {out.name} ({len(note)} chars, {stop})")
    return out


# --------------------------------------------------------------------------- concept notes
CONCEPT_SYS = """You write concise Obsidian concept notes for a Wharton MBA student.
For each concept you are given (with the course and the sessions where it appears), output a note.

Separate notes with a line containing only: @@@
Begin each note with a line: ===CONCEPT=== <exact concept name>
Then the note: YAML frontmatter then body.

Frontmatter:
---
title: "<concept name>"
type: concept
course: "<course code>"
tags: [concept, <1-3 kebab tags>]
aliases: [<common variants/abbreviations, optional>]
---

Body: a clear, complete definition; why it matters in THIS course; key formula/example if applicable; and a `## Related` line with [[wikilinks]] to closely related concepts. Then `## Referenced in` with a bullet [[link]] to each session provided. Be precise and useful, not padded."""


def generate_concept_notes(course_dir: Path, client) -> int:
    code, _ = parse_course(course_dir.name)
    # collect concept -> [session titles]
    concept_sessions: dict[str, list[str]] = {}
    for sdir in session_folders(course_dir):
        note = sdir / f"{sdir.name}.md"
        if not note.exists():
            continue
        for c in parse_concepts(note.read_text(encoding="utf-8")):
            concept_sessions.setdefault(c, [])
            if sdir.name not in concept_sessions[c]:
                concept_sessions[c].append(sdir.name)
    if not concept_sessions:
        return 0
    cdir = course_dir / "Concepts"
    cdir.mkdir(exist_ok=True)

    items = sorted(concept_sessions.items())
    BATCH = 12
    written = 0
    for i in range(0, len(items), BATCH):
        batch = items[i:i + BATCH]
        user = f"Course: {code} — {parse_course(course_dir.name)[1]}\n\nConcepts to write:\n"
        for name, sess in batch:
            user += f"\n- {name}  (appears in: {', '.join(sess)})"
        text, _ = stream_completion(client, CONCEPT_SYS, user, max_tokens=16000)
        for chunk in text.split("@@@"):
            mm = re.search(r"===CONCEPT===\s*(.+)", chunk)
            if not mm:
                continue
            cname = mm.group(1).strip().splitlines()[0].strip()
            body = chunk[chunk.index(mm.group(0)) + len(mm.group(0)):].lstrip("\n")
            safe = re.sub(r'[<>:"/\\|?*]', "-", cname).strip()
            (cdir / f"{safe}.md").write_text(body.strip() + "\n", encoding="utf-8")
            written += 1
        print(f"  concept batch {i // BATCH + 1}: total written {written}")
    return written


# --------------------------------------------------------------------------- MOC + master
MOC_SYS = """You write an Obsidian Map-of-Content (MOC) index note for a Wharton course, synthesising across its sessions.
Output YAML frontmatter (title "<code> - MOC", type: moc, course, tags) then:
# <course code> — <course name> (Map of Content)
## Course Overview  (synthesised arc of the whole course)
## Sessions  (a table or list: each links [[session note title]] with a one-line summary, in order)
## Major Themes & Through-Lines  (cross-session synthesis, link [[concepts]])
## Key Frameworks Across the Course
## Exam / Final Prep  (the most important things to master)
Use [[wikilinks]] for sessions and concepts. Be substantive."""


def generate_moc(course_dir: Path, client, course_resources_text: str = "") -> None:
    code, name = parse_course(course_dir.name)
    digest = []
    for sdir in session_folders(course_dir):
        note = sdir / f"{sdir.name}.md"
        if not note.exists():
            continue
        md = note.read_text(encoding="utf-8")
        _, body = split_frontmatter(md)
        overview = ""
        om = re.search(r"##\s*Overview\s*\n(.+?)(\n##\s|\Z)", body, re.S)
        if om:
            overview = om.group(1).strip()[:1500]
        heads = re.findall(r"^##\s+(.+)$", body, re.M)
        digest.append(f"### [[{sdir.name}]]\nConcepts: {', '.join(parse_concepts(md))}\n"
                      f"Overview: {overview}\nSections: {', '.join(heads)}")
    user = f"Course: {code} — {name}\n\nSESSION DIGESTS:\n\n" + "\n\n".join(digest)
    if course_resources_text.strip():
        user += ("\n\nCOURSE-LEVEL MATERIAL (syllabus / past exams / general readings — use to "
                 "ground the Exam / Final Prep section):\n" + course_resources_text[:50000])
    text, _ = stream_completion(client, MOC_SYS, user, max_tokens=12000)
    (course_dir / f"{code} - MOC.md").write_text(text, encoding="utf-8")
    print(f"  wrote {code} - MOC.md")


def generate_master(course_dir: Path) -> None:
    code, name = parse_course(course_dir.name)
    parts = [f"---\ntitle: \"{code} - Master Notes\"\ntype: master\ncourse: \"{name}\"\n"
             f"tags: [{re.sub(r'[^a-z0-9]+','-',code.lower())}, master]\n---\n",
             f"# {code} — {name}: Master Notes\n",
             f"> Compiled from the individual session notes. See also [[{code} - MOC]].\n",
             "## Contents"]
    bodies = []
    for sdir in session_folders(course_dir):
        note = sdir / f"{sdir.name}.md"
        if not note.exists():
            continue
        _, body = split_frontmatter(note.read_text(encoding="utf-8"))
        body = re.sub(r"^>\s*Part of .*$", "", body, flags=re.M).strip()
        parts.append(f"- [[{sdir.name}]]")
        bodies.append("\n\n---\n\n" + body)
    out = "\n".join(parts) + "\n" + "".join(bodies) + "\n"
    (course_dir / f"{code} - Master Notes.md").write_text(out, encoding="utf-8")
    print(f"  wrote {code} - Master Notes.md")


# --------------------------------------------------------------------------- orchestration
def build_course(course_dir: Path, client) -> None:
    code, _ = parse_course(course_dir.name)
    print(f"\n=== BUILD {course_dir.name} ===")
    mapping = map_resources(course_dir, client)
    # invert mapping: session folder name -> [absolute resource paths]
    by_session: dict[str, list[Path]] = {}
    for bucket, files in mapping.items():
        for rel in files:
            by_session.setdefault(bucket, []).append(course_dir / rel)

    for sdir in session_folders(course_dir):
        extra = by_session.get(sdir.name, [])
        generate_session_note(course_dir, sdir, extra, client)

    n = generate_concept_notes(course_dir, client)
    print(f"  concept notes: {n}")
    course_text = ""
    for p in by_session.get("course", []):
        if p.exists():
            course_text += f"\n\n[{p.name}]\n" + extract_text(p)
    generate_moc(course_dir, client, course_text)
    generate_master(course_dir)

    # archive old consolidated notes
    old = course_dir / f"{code} - Notes.md"
    if old.exists():
        old.rename(course_dir / f"{code} - Notes (consolidated archive).md")
        print("  archived old consolidated notes")
    print(f"=== DONE {course_dir.name} ===")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", help="absolute path to a single session folder")
    ap.add_argument("--course", help="course folder name under the notes root")
    args = ap.parse_args()
    client = client_factory()

    if args.one:
        sd = Path(args.one)
        generate_session_note(sd.parent, sd, [], client)
    elif args.course:
        build_course(NOTES_ROOT / args.course, client)
    else:
        print("Provide --course '<folder>' or --one '<session path>'.")


if __name__ == "__main__":
    main()
