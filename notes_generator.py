"""Generate structured study notes from lecture transcript + materials using Claude."""

import logging
import os

import anthropic

logger = logging.getLogger("study_notes.notes")

# Safety guards only — large enough to pass a full lecture + slides through untouched.
MAX_TRANSCRIPT_CHARS = 600_000
MAX_MATERIAL_CHARS = 80_000

_SYSTEM_PROMPT = """You are an expert study notes writer for an MBA student at Wharton.
Given a FULL lecture transcript and supporting materials (slides, readings, cases),
produce comprehensive, faithful study notes in Markdown. These are study notes, not a
summary: the goal is to capture everything of substance the professor covered so the
student never has to re-watch the lecture.

Coverage requirements (most important):
- Capture EVERY concept, definition, framework, model, case, example, numerical detail,
  rule, and piece of advice the professor presents. Do not omit or compress a topic
  because the notes are getting long — length should scale with the richness of the
  lecture. A 2-3 hour lecture should produce thorough, detailed notes.
- Work through the lecture in the order topics are introduced, so nothing late in the
  transcript is dropped.
- Preserve the professor's specific terminology, examples, numbers, named cases, and
  named people. Quote memorable phrasings where useful.
- Whenever the professor enumerates or classifies ("there are three types of...",
  "the steps are..."), reproduce the FULL list with each item explained and its examples.
- Include assignment instructions, templates, grading rules, due dates, and logistics
  exactly as stated.

Organize the notes under these headings:
1. **Session Summary** — bullet points capturing the core theses of the lecture
2. **Key Concepts** — each concept with a definition and why it matters
3. **Frameworks & Models** — frameworks, matrices, typologies, or models introduced
4. **Case Studies / Examples** — examples discussed, with the lesson drawn
5. **Action Items / Takeaways** — concrete things to remember or apply
6. **Exam / Discussion Prep** — likely exam or cold-call questions with full answers

Be specific and analytical, never generic. Flag concepts that connect to other Wharton
courses. Prefer completeness over brevity — do not artificially limit the number of
bullets, concepts, examples, or questions."""


class NotesGenerator:
    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def generate(
        self,
        course_name: str,
        session_name: str,
        transcript: str,
        materials: list[dict],
        max_tokens: int = 16000,
    ) -> str:
        """Return markdown study notes. materials is a list of {name, text} dicts."""

        if not transcript and not materials:
            return f"# {session_name}\n\n_No transcript or materials available for this session._\n"

        # Build user message
        parts = [f"**Course:** {course_name}", f"**Session:** {session_name}", ""]

        if transcript:
            parts.append("## Lecture Transcript")
            # Send the full transcript. A 2-3 hour lecture is ~100k chars (~25k tokens),
            # well within the 200k context window. The high cap is only a safety guard
            # against pathological inputs, not a content-shaping limit.
            parts.append(transcript[:MAX_TRANSCRIPT_CHARS])
            parts.append("")

        for mat in materials:
            parts.append(f"## Material: {mat['name']}")
            parts.append(mat["text"][:MAX_MATERIAL_CHARS])
            parts.append("")

        user_content = "\n".join(parts)

        logger.info(
            "Generating notes for '%s' / '%s' (%d chars input)",
            course_name,
            session_name,
            len(user_content),
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )

        notes = response.content[0].text
        logger.info("Notes generated (%d chars)", len(notes))
        return notes
