"""Generate structured study notes from lecture transcript + materials using Claude."""

import logging
import os

import anthropic

logger = logging.getLogger("study_notes.notes")

_SYSTEM_PROMPT = """You are an expert study notes writer for an MBA student at Wharton.
Given a lecture transcript and supporting materials (slides, readings, cases), produce
clear, well-structured study notes in Markdown.

Structure every set of notes as follows:
1. **Session Summary** — 3-5 bullet points capturing the core thesis of the lecture
2. **Key Concepts** — each concept with a 1-2 sentence definition and why it matters
3. **Frameworks & Models** — any frameworks, matrices, or models introduced (name + brief description)
4. **Case Studies / Examples** — real-world examples discussed, with the lesson drawn
5. **Action Items / Takeaways** — concrete things to remember or apply
6. **Exam / Discussion Prep** — 3-5 likely exam or cold-call questions with brief answers

Be specific. Use the professor's language where possible. Flag any concepts that
connect to other Wharton courses. Keep the tone analytical, not generic."""


class NotesGenerator:
    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def generate(
        self,
        course_name: str,
        session_name: str,
        transcript: str,
        materials: list[dict],
        max_tokens: int = 2048,
    ) -> str:
        """Return markdown study notes. materials is a list of {name, text} dicts."""

        if not transcript and not materials:
            return f"# {session_name}\n\n_No transcript or materials available for this session._\n"

        # Build user message
        parts = [f"**Course:** {course_name}", f"**Session:** {session_name}", ""]

        if transcript:
            parts.append("## Lecture Transcript")
            parts.append(transcript[:12000])  # cap to control token usage
            parts.append("")

        for mat in materials:
            parts.append(f"## Material: {mat['name']}")
            parts.append(mat["text"][:6000])
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
