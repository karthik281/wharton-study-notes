"""Tests for agent.py"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("CANVAS_URL", "https://canvas.upenn.edu")
os.environ.setdefault("CANVAS_API_TOKEN", "test-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("PANOPTO_COOKIE", ".ASPXAUTH=test")

from unittest.mock import MagicMock, patch
import pytest
from agent import (
    _safe,
    session_dir,
    validate_config,
    OUTPUT_DIR,
    course_notes_path,
    append_session_notes,
    process_panopto_session,
    dedup_sessions,
)


class TestSafeFilename:
    def test_removes_forbidden_chars(self):
        assert _safe('Course: "Strategy" <2026>') == "Course- -Strategy- -2026-"

    def test_preserves_normal_chars(self):
        assert _safe("MGMT 6100 - Strategy") == "MGMT 6100 - Strategy"

    def test_strips_whitespace(self):
        assert _safe("  name  ") == "name"


class TestSessionDir:
    def test_creates_directory(self, tmp_path):
        with patch("agent.OUTPUT_DIR", tmp_path):
            folder = session_dir("MGMT6100 - Strategy", "Week 5")
        assert folder.exists()
        assert (folder / "materials").exists()

    def test_path_contains_course_and_module(self, tmp_path):
        with patch("agent.OUTPUT_DIR", tmp_path):
            folder = session_dir("MGMT6100 - Strategy", "Week 5 Session")
        assert "MGMT6100" in str(folder)
        assert "Week 5 Session" in str(folder)


class TestValidateConfig:
    def test_passes_with_all_vars(self, monkeypatch):
        monkeypatch.setenv("CANVAS_URL", "https://canvas.upenn.edu")
        monkeypatch.setenv("CANVAS_API_TOKEN", "token")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        monkeypatch.setenv("PANOPTO_COOKIE", "test")
        validate_config()  # should not raise

    def test_passes_without_canvas_token(self, monkeypatch):
        # Canvas is optional -- validate_config should not raise
        monkeypatch.delenv("CANVAS_URL", raising=False)
        monkeypatch.delenv("CANVAS_API_TOKEN", raising=False)
        monkeypatch.setenv("PANOPTO_COOKIE", "test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        validate_config()  # should not raise

    def test_raises_on_missing_anthropic_key(self, monkeypatch):
        monkeypatch.setenv("CANVAS_URL", "https://canvas.upenn.edu")
        monkeypatch.setenv("CANVAS_API_TOKEN", "token")
        monkeypatch.setenv("PANOPTO_COOKIE", "test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            validate_config()

    def test_raises_on_missing_panopto_credentials(self, monkeypatch):
        # Panopto is required
        monkeypatch.delenv("PANOPTO_COOKIE", raising=False)
        monkeypatch.delenv("PANOPTO_CLIENT_ID", raising=False)
        monkeypatch.delenv("PANOPTO_CLIENT_SECRET", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        with pytest.raises(EnvironmentError, match="Panopto"):
            validate_config()


class TestProcessSession:
    def test_skips_when_notes_already_exist(self, tmp_path):
        from agent import process_session
        canvas = MagicMock()
        panopto = MagicMock()
        generator = MagicMock()
        course = MagicMock()
        course.name = "MGMT6100"
        module = MagicMock()
        module.name = "Week 1"

        with patch("agent.OUTPUT_DIR", tmp_path):
            folder = session_dir("MGMT6100", "Week 1")
            (folder / "notes.md").write_text("existing notes")
            process_session(canvas, panopto, generator, course, module)

        generator.generate.assert_not_called()

    def test_saves_notes_to_file(self, tmp_path):
        from agent import process_session
        canvas = MagicMock()
        canvas.get_module_items.return_value = []
        canvas.collect_panopto_ids.return_value = []

        generator = MagicMock()
        generator.generate.return_value = "# Generated Notes"

        course = MagicMock()
        course.name = "TEST6100"
        module = MagicMock()
        module.name = "Test Session"

        # Provide fake materials so the agent doesn't short-circuit on empty content
        fake_materials = [{"name": "slides.pdf", "text": "slide content"}]
        with patch("agent.OUTPUT_DIR", tmp_path):
            with patch("file_processor.summarise_materials", return_value=fake_materials):
                process_session(canvas, None, generator, course, module)
            folder = session_dir("TEST6100", "Test Session")

        notes_path = folder / "notes.md"
        assert notes_path.exists()
        assert notes_path.read_text() == "# Generated Notes"


class TestCourseNotesPath:
    def test_extracts_course_code_oidd(self, tmp_path):
        """course_notes_path should extract OIDD 6360 from a full course name."""
        with patch("agent.OUTPUT_DIR", tmp_path):
            path = course_notes_path("OIDD 6360 (51 Global) - Summer 2026")
        assert path.name == "OIDD 6360 - Notes.md"

    def test_extracts_course_code_fnce(self, tmp_path):
        """course_notes_path should extract FNCE 7310 from a full course name."""
        with patch("agent.OUTPUT_DIR", tmp_path):
            path = course_notes_path("FNCE 7310 (51 Global) - Summer 2026")
        assert path.name == "FNCE 7310 - Notes.md"

    def test_creates_directory(self, tmp_path):
        """course_notes_path should create the parent course directory."""
        with patch("agent.OUTPUT_DIR", tmp_path):
            path = course_notes_path("MGMT 8150 - Strategy")
        assert path.parent.exists()

    def test_fallback_when_no_course_code(self, tmp_path):
        """When no course code pattern found, uses sanitised course name."""
        with patch("agent.OUTPUT_DIR", tmp_path):
            path = course_notes_path("My Special Seminar")
        # Should still return a .md file and not crash
        assert path.suffix == ".md"

    def test_extracts_mgmt_code(self, tmp_path):
        """course_notes_path handles MGMT prefix."""
        with patch("agent.OUTPUT_DIR", tmp_path):
            path = course_notes_path("MGMT 6100 - Strategic Management")
        assert path.name == "MGMT 6100 - Notes.md"


class TestAppendSessionNotes:
    def test_first_session_no_leading_separator(self, tmp_path):
        """Fresh file: first session appended should have no leading --- separator."""
        with patch("agent.OUTPUT_DIR", tmp_path):
            path = append_session_notes(
                "OIDD 6360 (51 Global) - Summer 2026",
                "Week 1 - Intro to Operations",
                "# Notes\nSome content here."
            )
        content = path.read_text(encoding="utf-8")
        assert not content.startswith("---")
        assert "<!-- session: Week 1 - Intro to Operations -->" in content

    def test_second_session_has_separator(self, tmp_path):
        """File with one session already: second session should have --- separator."""
        with patch("agent.OUTPUT_DIR", tmp_path):
            append_session_notes(
                "OIDD 6360 (51 Global) - Summer 2026",
                "Week 1 - Intro",
                "# Notes Week 1"
            )
            path = append_session_notes(
                "OIDD 6360 (51 Global) - Summer 2026",
                "Week 2 - Deep Dive",
                "# Notes Week 2"
            )
        content = path.read_text(encoding="utf-8")
        assert "---" in content
        assert "<!-- session: Week 1 - Intro -->" in content
        assert "<!-- session: Week 2 - Deep Dive -->" in content

    def test_notes_content_preserved(self, tmp_path):
        """Notes text should appear verbatim after the session header."""
        with patch("agent.OUTPUT_DIR", tmp_path):
            path = append_session_notes(
                "FNCE 7310 - Finance",
                "Session 3 - Bonds",
                "## Key Concepts\n- Duration\n- Convexity"
            )
        content = path.read_text(encoding="utf-8")
        assert "## Key Concepts" in content
        assert "- Duration" in content


class TestIdempotency:
    def test_process_panopto_session_skips_existing(self, tmp_path):
        """process_panopto_session should skip if session marker already in notes file."""
        panopto = MagicMock()
        generator = MagicMock()

        course_name = "OIDD 6360 - Operations"
        session_name = "Week 5 - Queuing Theory"

        with patch("agent.OUTPUT_DIR", tmp_path):
            # Pre-write the notes file with the session marker
            notes_path = course_notes_path(course_name)
            notes_path.write_text(
                f"<!-- session: {session_name} -->\n\n# Existing notes\n",
                encoding="utf-8"
            )
            # Now try to process the same session
            process_panopto_session(panopto, generator, "session-id-abc", course_name, session_name)

        # Should not fetch transcript or generate notes
        panopto.get_transcript.assert_not_called()
        generator.generate.assert_not_called()

    def test_process_panopto_session_processes_new(self, tmp_path):
        """process_panopto_session should process when session not yet in notes."""
        panopto = MagicMock()
        panopto.get_transcript.return_value = "Lecture content here."

        generator = MagicMock()
        generator.generate.return_value = "# Generated Notes\nContent."

        course_name = "MGMT 6100 - Strategy"
        session_name = "Week 3 - Porter"

        with patch("agent.OUTPUT_DIR", tmp_path):
            process_panopto_session(panopto, generator, "session-id-xyz", course_name, session_name)
            notes_path = course_notes_path(course_name)

        assert notes_path.exists()
        content = notes_path.read_text(encoding="utf-8")
        assert f"<!-- session: {session_name} -->" in content
        assert "# Generated Notes" in content


class TestDedupSessions:
    def _panopto(self, transcripts):
        p = MagicMock()
        p.get_transcript.side_effect = lambda sid: transcripts.get(sid, "")
        return p

    def test_drops_incomplete_recording(self):
        sessions = [
            {"Id": "a", "SessionName": "06/12 7am | FNCE 7310 (51 Global) - Su26 - Not Complete"},
            {"Id": "b", "SessionName": "FNCE7310 Session 5 (06/12) Su26 - Complete Video"},
        ]
        kept = dedup_sessions(self._panopto({}), sessions)
        ids = [s["Id"] for s in kept]
        assert ids == ["b"]

    def test_keeps_longest_transcript_among_duplicates(self):
        name = "6/13 7-10 am OIDD/MGMT 6910 & LGST 8060 (51 Global) - Summer 2026"
        sessions = [
            {"Id": "short", "SessionName": name},
            {"Id": "full", "SessionName": name},
        ]
        panopto = self._panopto({"short": "x" * 11000, "full": "x" * 79000})
        kept = dedup_sessions(panopto, sessions)
        assert [s["Id"] for s in kept] == ["full"]

    def test_distinct_sessions_all_kept_in_order(self):
        sessions = [
            {"Id": "1", "SessionName": "05/30 7am | OIDD 6360 (51 Global) - Summer 2026"},
            {"Id": "2", "SessionName": "05/29 7am | FNCE 7310 (51 Global) - Summer 2026"},
            {"Id": "3", "SessionName": "5/28 7-10 pm OIDD/MGMT 6910 & LGST 8060 (51 Global) - Summer 2026"},
        ]
        kept = dedup_sessions(self._panopto({}), sessions)
        assert [s["Id"] for s in kept] == ["1", "2", "3"]

    def test_same_date_different_course_not_merged(self):
        # OIDD 5/29 and FNCE 5/29 share a date but are different courses.
        sessions = [
            {"Id": "oidd", "SessionName": "05/29 7PM | OIDD 6360 (51 Global) - Summer 2026"},
            {"Id": "fnce", "SessionName": "05/29 7am | FNCE 7310 (51 Global) - Summer 2026"},
        ]
        kept = dedup_sessions(self._panopto({}), sessions)
        assert {s["Id"] for s in kept} == {"oidd", "fnce"}
