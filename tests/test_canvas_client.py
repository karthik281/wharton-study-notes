"""Tests for canvas_client.py"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch, PropertyMock
from canvas_client import CanvasClient, _PANOPTO_ID_RE


class TestPanoptoIdRegex:
    def test_extracts_from_viewer_url(self):
        url = "https://upenn.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id=abc123de-0000-0000-0000-000000000001"
        m = _PANOPTO_ID_RE.search(url)
        assert m is not None
        assert m.group(1) == "abc123de-0000-0000-0000-000000000001"

    def test_extracts_from_embed_url(self):
        html = '<iframe src="https://upenn.hosted.panopto.com/Panopto/Pages/Embed.aspx?id=ffffffff-1111-2222-3333-444444444444&autoplay=false">'
        m = _PANOPTO_ID_RE.search(html)
        assert m is not None
        assert m.group(1) == "ffffffff-1111-2222-3333-444444444444"

    def test_no_match_on_plain_text(self):
        assert _PANOPTO_ID_RE.search("no panopto here") is None

    def test_case_insensitive(self):
        url = "https://example.com?ID=ABCDEF12-0000-0000-0000-000000000000"
        m = _PANOPTO_ID_RE.search(url)
        assert m is not None


class TestCanvasClient:
    def _make_client(self):
        with patch("canvas_client.Canvas"):
            return CanvasClient("https://canvas.upenn.edu", "test-token")

    def test_extract_panopto_id_from_item_url(self):
        client = self._make_client()
        item = MagicMock()
        item.url = "https://upenn.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id=aabbccdd-0000-0000-0000-111111111111"
        item.external_url = ""
        result = client.extract_panopto_id(item)
        assert result == "aabbccdd-0000-0000-0000-111111111111"

    def test_extract_panopto_id_returns_none_when_absent(self):
        client = self._make_client()
        item = MagicMock()
        item.url = "https://canvas.upenn.edu/courses/123"
        item.external_url = ""
        result = client.extract_panopto_id(item)
        assert result is None

    def test_extract_panopto_id_from_html(self):
        client = self._make_client()
        html = '<iframe src="https://upenn.hosted.panopto.com/Panopto/Pages/Embed.aspx?id=99999999-aaaa-bbbb-cccc-dddddddddddd"></iframe>'
        result = client.extract_panopto_id_from_html(html)
        assert result == "99999999-aaaa-bbbb-cccc-dddddddddddd"

    def test_extract_panopto_id_from_html_returns_none(self):
        client = self._make_client()
        assert client.extract_panopto_id_from_html("<p>No video here</p>") is None

    def test_get_latest_module_returns_last(self):
        client = self._make_client()
        m1, m2, m3 = MagicMock(), MagicMock(), MagicMock()
        m1.published = True
        m2.published = True
        m3.published = True
        course = MagicMock()
        course.get_modules.return_value = [m1, m2, m3]
        course.name = "Test Course"
        result = client.get_latest_module(course)
        assert result is m3

    def test_get_latest_module_returns_none_when_empty(self):
        client = self._make_client()
        course = MagicMock()
        course.get_modules.return_value = []
        course.name = "Empty Course"
        result = client.get_latest_module(course)
        assert result is None

    def test_collect_panopto_ids_deduplicates(self):
        client = self._make_client()
        course = MagicMock()

        shared_id = "12345678-0000-0000-0000-000000000000"
        item1 = MagicMock()
        item1.type = "ExternalTool"
        item1.url = f"https://upenn.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id={shared_id}"
        item1.external_url = ""

        item2 = MagicMock()
        item2.type = "ExternalTool"
        item2.url = f"https://upenn.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id={shared_id}"
        item2.external_url = ""

        result = client.collect_panopto_ids(course, [item1, item2])
        assert result == [shared_id]

    def test_download_file_skips_existing(self, tmp_path):
        client = self._make_client()
        dest = tmp_path / "existing.pdf"
        dest.write_bytes(b"content")
        result = client.download_file("http://example.com/file.pdf", "existing.pdf", tmp_path)
        assert result == dest

    def test_download_module_item_file_ignores_non_file(self):
        client = self._make_client()
        item = MagicMock()
        item.type = "Page"
        result = client.download_module_item_file(item, MagicMock())
        assert result is None
