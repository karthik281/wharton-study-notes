"""Tests for notes_generator.py"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from unittest.mock import MagicMock, patch
from notes_generator import NotesGenerator


class TestNotesGenerator:
    def _make_gen(self):
        return NotesGenerator(api_key="test-key")

    def test_returns_placeholder_when_no_content(self):
        gen = self._make_gen()
        result = gen.generate("MGMT6100", "Week 1", transcript="", materials=[])
        assert "No transcript or materials" in result
        assert "Week 1" in result

    def test_calls_anthropic_with_transcript(self):
        gen = self._make_gen()
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="# Notes\n\n- Point 1")]

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = mock_resp
            gen2 = NotesGenerator(api_key="test-key")
            result = gen2.generate("MGMT6100", "Week 1", transcript="Hello world", materials=[])

        assert result == "# Notes\n\n- Point 1"
        mock_cls.return_value.messages.create.assert_called_once()

    def test_includes_materials_in_prompt(self):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="notes")]
        materials = [{"name": "slides.pdf", "text": "slide content here"}]

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = mock_resp
            gen = NotesGenerator(api_key="test-key")
            gen.generate("Course", "Session", transcript="t", materials=materials)

        call_kwargs = mock_cls.return_value.messages.create.call_args[1]
        user_content = call_kwargs["messages"][0]["content"]
        assert "slides.pdf" in user_content
        assert "slide content here" in user_content

    def test_uses_prompt_caching(self):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="notes")]

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = mock_resp
            gen = NotesGenerator(api_key="test-key")
            gen.generate("Course", "Session", transcript="t", materials=[])

        call_kwargs = mock_cls.return_value.messages.create.call_args[1]
        system = call_kwargs["system"]
        assert any(
            block.get("cache_control", {}).get("type") == "ephemeral"
            for block in system
        )

    def test_uses_sonnet_model_by_default(self):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="notes")]

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = mock_resp
            gen = NotesGenerator(api_key="test-key")
            gen.generate("Course", "Session", transcript="t", materials=[])

        call_kwargs = mock_cls.return_value.messages.create.call_args[1]
        assert "sonnet" in call_kwargs["model"]

    def test_full_transcript_passed_without_truncation(self):
        """A normal full-length lecture (~100k chars) must pass through intact."""
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="notes")]
        long_transcript = "x" * 100000

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = mock_resp
            gen = NotesGenerator(api_key="test-key")
            gen.generate("Course", "Session", transcript=long_transcript, materials=[])

        call_kwargs = mock_cls.return_value.messages.create.call_args[1]
        user_content = call_kwargs["messages"][0]["content"]
        assert user_content.count("x") == 100000

    def test_pathological_transcript_capped_by_safety_guard(self):
        """Inputs beyond the safety guard are capped to avoid runaway token usage."""
        from notes_generator import MAX_TRANSCRIPT_CHARS

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="notes")]
        huge_transcript = "x" * (MAX_TRANSCRIPT_CHARS + 50000)

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = mock_resp
            gen = NotesGenerator(api_key="test-key")
            gen.generate("Course", "Session", transcript=huge_transcript, materials=[])

        call_kwargs = mock_cls.return_value.messages.create.call_args[1]
        user_content = call_kwargs["messages"][0]["content"]
        assert user_content.count("x") == MAX_TRANSCRIPT_CHARS

    def test_uses_high_output_token_budget(self):
        """Notes need room to be comprehensive, not capped at ~80 lines."""
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="notes")]

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = mock_resp
            gen = NotesGenerator(api_key="test-key")
            gen.generate("Course", "Session", transcript="t", materials=[])

        call_kwargs = mock_cls.return_value.messages.create.call_args[1]
        assert call_kwargs["max_tokens"] >= 8192
