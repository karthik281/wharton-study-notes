"""Tests for file_processor.py"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from file_processor import (
    extract_pdf_text,
    extract_pptx_text,
    extract_docx_text,
    extract_text,
    summarise_materials,
    SUPPORTED_EXTENSIONS,
)


class TestExtractPdfText:
    def test_extracts_text_from_pages(self, tmp_path):
        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page content here"
        mock_reader.pages = [mock_page, mock_page]

        with patch("file_processor.PdfReader", return_value=mock_reader):
            result = extract_pdf_text(tmp_path / "test.pdf")

        assert "Page content here" in result
        assert "[Page 1]" in result
        assert "[Page 2]" in result

    def test_skips_empty_pages(self, tmp_path):
        mock_reader = MagicMock()
        empty_page = MagicMock()
        empty_page.extract_text.return_value = "   "
        content_page = MagicMock()
        content_page.extract_text.return_value = "Real content"
        mock_reader.pages = [empty_page, content_page]

        with patch("file_processor.PdfReader", return_value=mock_reader):
            result = extract_pdf_text(tmp_path / "test.pdf")

        assert "[Page 1]" not in result
        assert "[Page 2]" in result

    def test_returns_empty_on_exception(self, tmp_path):
        with patch("file_processor.PdfReader", side_effect=Exception("corrupt")):
            result = extract_pdf_text(tmp_path / "bad.pdf")
        assert result == ""


class TestExtractPptxText:
    def _make_prs(self, slide_texts: list[list[str]]):
        prs = MagicMock()
        slides = []
        for texts in slide_texts:
            slide = MagicMock()
            shapes = []
            for text in texts:
                shape = MagicMock()
                shape.has_text_frame = True
                para = MagicMock()
                run = MagicMock()
                run.text = text
                para.runs = [run]
                shape.text_frame.paragraphs = [para]
                shapes.append(shape)
            slide.shapes = shapes
            slides.append(slide)
        prs.slides = slides
        return prs

    def test_extracts_slide_text(self, tmp_path):
        prs = self._make_prs([["Title"], ["Bullet 1", "Bullet 2"]])
        with patch("file_processor.Presentation", return_value=prs):
            result = extract_pptx_text(tmp_path / "deck.pptx")
        assert "Title" in result
        assert "Bullet 1" in result
        assert "[Slide 1]" in result

    def test_returns_empty_on_exception(self, tmp_path):
        with patch("file_processor.Presentation", side_effect=Exception("corrupt")):
            result = extract_pptx_text(tmp_path / "bad.pptx")
        assert result == ""


class TestExtractDocxText:
    def test_extracts_paragraphs(self, tmp_path):
        doc = MagicMock()
        p1 = MagicMock(); p1.text = "First paragraph"
        p2 = MagicMock(); p2.text = "   "
        p3 = MagicMock(); p3.text = "Third paragraph"
        doc.paragraphs = [p1, p2, p3]
        with patch("file_processor.Document", return_value=doc):
            result = extract_docx_text(tmp_path / "doc.docx")
        assert "First paragraph" in result
        assert "Third paragraph" in result

    def test_returns_empty_on_exception(self, tmp_path):
        with patch("file_processor.Document", side_effect=Exception("corrupt")):
            result = extract_docx_text(tmp_path / "bad.docx")
        assert result == ""


class TestExtractText:
    def test_routes_pdf(self, tmp_path):
        p = tmp_path / "file.pdf"
        p.touch()
        with patch("file_processor.extract_pdf_text", return_value="pdf text") as m:
            assert extract_text(p) == "pdf text"
            m.assert_called_once_with(p)

    def test_routes_pptx(self, tmp_path):
        p = tmp_path / "file.pptx"
        p.touch()
        with patch("file_processor.extract_pptx_text", return_value="pptx text") as m:
            assert extract_text(p) == "pptx text"

    def test_routes_docx(self, tmp_path):
        p = tmp_path / "file.docx"
        p.touch()
        with patch("file_processor.extract_docx_text", return_value="docx text") as m:
            assert extract_text(p) == "docx text"

    def test_reads_txt(self, tmp_path):
        p = tmp_path / "notes.txt"
        p.write_text("plain text content", encoding="utf-8")
        assert extract_text(p) == "plain text content"

    def test_returns_empty_for_unsupported(self, tmp_path):
        p = tmp_path / "image.png"
        p.touch()
        assert extract_text(p) == ""


class TestSummariseMaterials:
    def test_filters_unsupported_extensions(self, tmp_path):
        png = tmp_path / "image.png"
        png.touch()
        result = summarise_materials([png])
        assert result == []

    def test_includes_supported_files(self, tmp_path):
        pdf = tmp_path / "slides.pdf"
        pdf.touch()
        with patch("file_processor.extract_text", return_value="some content"):
            result = summarise_materials([pdf])
        assert len(result) == 1
        assert result[0]["name"] == "slides.pdf"
        assert result[0]["text"] == "some content"

    def test_skips_files_with_empty_text(self, tmp_path):
        pdf = tmp_path / "empty.pdf"
        pdf.touch()
        with patch("file_processor.extract_text", return_value=""):
            result = summarise_materials([pdf])
        assert result == []

    def test_truncates_to_max_chars(self, tmp_path):
        pdf = tmp_path / "long.pdf"
        pdf.touch()
        with patch("file_processor.extract_text", return_value="x" * 20000):
            result = summarise_materials([pdf], max_chars_per_file=100)
        assert len(result[0]["text"]) == 100
