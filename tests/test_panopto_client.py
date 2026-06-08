"""Tests for panopto_client.py"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import requests
from unittest.mock import MagicMock, patch
from panopto_client import PanoptoClient, PanoptoAuthError


def _make_client(**kwargs):
    defaults = dict(
        server="upenn.hosted.panopto.com",
        client_id="cid",
        client_secret="csec",
        username="user",
        password="pass",
    )
    defaults.update(kwargs)
    return PanoptoClient(**defaults)


def _mock_response(json_data=None, status=200, text=""):
    mock = MagicMock()
    mock.status_code = status
    mock.ok = status < 400
    mock.json.return_value = json_data or {}
    mock.text = text
    mock.raise_for_status = MagicMock()
    if status >= 400:
        mock.raise_for_status.side_effect = requests.HTTPError(response=mock)
    return mock


class TestAuthentication:
    def test_oauth_success(self):
        client = _make_client()
        token_resp = _mock_response({"access_token": "tok123", "expires_in": 3600})
        with patch.object(client._session, "post", return_value=token_resp):
            client._authenticate_oauth()
        assert client._access_token == "tok123"
        assert "Authorization" in client._session.headers

    def test_oauth_failure_raises(self):
        client = _make_client()
        fail_resp = _mock_response(status=401)
        fail_resp.text = "Unauthorized"
        with patch.object(client._session, "post", return_value=fail_resp):
            with pytest.raises(PanoptoAuthError, match="OAuth2 password grant failed"):
                client._authenticate_oauth()

    def test_cookie_auth_sets_header(self):
        client = _make_client(cookie="PANOPTO_SESSION=abc123")
        client._authenticate_cookie()
        assert "Cookie" in client._session.headers

    def test_authenticate_prefers_cookie(self):
        client = _make_client(cookie="PANOPTO_SESSION=abc123")
        with patch.object(client, "_authenticate_cookie") as mock_cookie:
            with patch.object(client, "_authenticate_oauth") as mock_oauth:
                client.authenticate()
        mock_cookie.assert_called_once()
        mock_oauth.assert_not_called()

    def test_authenticate_falls_back_to_oauth(self):
        client = _make_client()
        with patch.object(client, "_authenticate_oauth") as mock_oauth:
            client.authenticate()
        mock_oauth.assert_called_once()

    def test_authenticate_raises_with_no_credentials(self):
        client = PanoptoClient(server="upenn.hosted.panopto.com")
        with pytest.raises(PanoptoAuthError, match="No Panopto credentials"):
            client.authenticate()


class TestTranscript:
    def test_returns_joined_text(self):
        client = _make_client()
        client._access_token = "tok"
        client._token_expiry = float("inf")
        transcript_data = {
            "Transcripts": [
                {"Lines": [{"Text": "Hello"}, {"Text": "world"}]},
            ]
        }
        with patch.object(client._session, "get", return_value=_mock_response(transcript_data)):
            result = client.get_transcript("session-id-123")
        assert result == "Hello world"

    def test_returns_empty_on_404(self):
        client = _make_client()
        client._access_token = "tok"
        client._token_expiry = float("inf")
        resp_404 = _mock_response(status=404)
        # 404 falls through to SRT fallback; mock SRT also empty
        with patch.object(client._session, "get", return_value=resp_404):
            result = client.get_transcript("missing-id")
        assert result == ""

    def test_returns_empty_on_no_transcript_key(self):
        client = _make_client()
        client._access_token = "tok"
        client._token_expiry = float("inf")
        with patch.object(client._session, "get", return_value=_mock_response({})):
            result = client.get_transcript("session-id")
        assert result == ""

    def test_skips_empty_lines(self):
        client = _make_client()
        client._access_token = "tok"
        client._token_expiry = float("inf")
        data = {
            "Transcripts": [{"Lines": [{"Text": "  "}, {"Text": "Real text"}, {"Text": ""}]}]
        }
        with patch.object(client._session, "get", return_value=_mock_response(data)):
            result = client.get_transcript("sid")
        assert result == "Real text"


class TestGetAllSessions:
    def test_returns_sessions_list(self):
        """Mock Data.svc POST returning 3 sessions -- verify list returned."""
        client = _make_client(cookie=".ASPXAUTH=abc")
        client._authenticate_cookie()

        page_data = {
            "d": {
                "Results": [
                    {"DeliveryID": "id-1", "SessionName": "Session A", "FolderName": "OIDD 6360"},
                    {"DeliveryID": "id-2", "SessionName": "Session B", "FolderName": "FNCE 7310"},
                    {"DeliveryID": "id-3", "SessionName": "Session C", "FolderName": "OIDD 6360"},
                ],
                "TotalNumber": 3,
            }
        }
        with patch.object(client._session, "post", return_value=_mock_response(page_data)):
            result = client.get_all_sessions(max_results=20)

        assert len(result) == 3
        assert result[0]["Id"] == "id-1"
        assert result[0]["SessionName"] == "Session A"
        assert result[0]["FolderName"] == "OIDD 6360"

    def test_respects_max_results(self):
        """Mock returns 50 sessions, max_results=5 -- verify only 5 returned."""
        client = _make_client(cookie=".ASPXAUTH=abc")
        client._authenticate_cookie()

        all_results = [
            {"DeliveryID": f"id-{i}", "SessionName": f"Session {i}", "FolderName": "Course"}
            for i in range(50)
        ]
        page_data = {"d": {"Results": all_results, "TotalNumber": 50}}

        with patch.object(client._session, "post", return_value=_mock_response(page_data)):
            result = client.get_all_sessions(max_results=5)

        assert len(result) == 5

    def test_handles_empty_results(self):
        """Mock returns empty Results -- verify empty list returned."""
        client = _make_client(cookie=".ASPXAUTH=abc")
        client._authenticate_cookie()

        page_data = {"d": {"Results": [], "TotalNumber": 0}}

        with patch.object(client._session, "post", return_value=_mock_response(page_data)):
            result = client.get_all_sessions(max_results=20)

        assert result == []

    def test_handles_request_error(self):
        """Mock raises requests.RequestException -- verify empty list returned."""
        client = _make_client(cookie=".ASPXAUTH=abc")
        client._authenticate_cookie()

        with patch.object(
            client._session, "post", side_effect=requests.RequestException("network error")
        ):
            result = client.get_all_sessions(max_results=20)

        assert result == []

    def test_deduplicates_by_id(self):
        """Duplicate DeliveryIDs should appear only once."""
        client = _make_client(cookie=".ASPXAUTH=abc")
        client._authenticate_cookie()

        page_data = {
            "d": {
                "Results": [
                    {"DeliveryID": "id-1", "SessionName": "Session A", "FolderName": "Course"},
                    {"DeliveryID": "id-1", "SessionName": "Session A duplicate", "FolderName": "Course"},
                    {"DeliveryID": "id-2", "SessionName": "Session B", "FolderName": "Course"},
                ],
                "TotalNumber": 3,
            }
        }
        with patch.object(client._session, "post", return_value=_mock_response(page_data)):
            result = client.get_all_sessions(max_results=20)

        assert len(result) == 2
        ids = [r["Id"] for r in result]
        assert ids == ["id-1", "id-2"]


class TestGetSessionInfo:
    def test_returns_session_metadata(self):
        """Mock DeliveryInfo JSON -- verify Id, SessionName, CourseName extracted."""
        client = _make_client(cookie=".ASPXAUTH=abc")
        client._authenticate_cookie()

        delivery_data = {
            "Delivery": {
                "SessionName": "Week 5 - Capital Structure",
                "SessionGroupLongName": "FNCE 7310 (51 Global) - Summer 2026",
                "Duration": 3600,
                "HasCaptions": True,
            }
        }
        with patch.object(client._session, "get", return_value=_mock_response(delivery_data)):
            result = client.get_session_info("session-uuid-abc")

        assert result["Id"] == "session-uuid-abc"
        assert result["SessionName"] == "Week 5 - Capital Structure"
        assert result["CourseName"] == "FNCE 7310 (51 Global) - Summer 2026"
        assert result["HasCaptions"] is True

    def test_handles_request_error(self):
        """Mock raises exception -- verify fallback dict returned with session_id."""
        client = _make_client(cookie=".ASPXAUTH=abc")
        client._authenticate_cookie()

        with patch.object(
            client._session, "get", side_effect=Exception("connection refused")
        ):
            result = client.get_session_info("session-uuid-xyz")

        assert result["Id"] == "session-uuid-xyz"
        # SessionName is built as "Session {session_id[:8]}" -> "Session session-"
        assert "Session" in result["SessionName"]
        assert result["CourseName"] == "Lectures"

    def test_uses_short_name_fallback(self):
        """When SessionGroupLongName is absent, use SessionGroupShortName."""
        client = _make_client(cookie=".ASPXAUTH=abc")
        client._authenticate_cookie()

        delivery_data = {
            "Delivery": {
                "SessionName": "Lecture 1",
                "SessionGroupLongName": "",
                "SessionGroupShortName": "MGMT 6100",
                "Duration": 0,
                "HasCaptions": False,
            }
        }
        with patch.object(client._session, "get", return_value=_mock_response(delivery_data)):
            result = client.get_session_info("sid-123")

        assert result["CourseName"] == "MGMT 6100"


class TestSRTTranscript:
    def test_parses_srt_correctly(self):
        """Input: valid SRT with timestamps and sequence numbers -- verify clean text output."""
        client = _make_client(cookie=".ASPXAUTH=abc")
        client._authenticate_cookie()

        srt_content = (
            "1\n"
            "00:00:01,000 --> 00:00:03,000\n"
            "Hello everyone welcome to class.\n"
            "\n"
            "2\n"
            "00:00:04,000 --> 00:00:06,500\n"
            "Today we discuss capital structure.\n"
            "\n"
            "3\n"
            "00:00:07,000 --> 00:00:09,000\n"
            "Let us begin.\n"
        )
        mock_resp = _mock_response(text=srt_content)
        mock_resp.text = srt_content

        with patch.object(client._session, "get", return_value=mock_resp):
            result = client._scrape_transcript_from_html("session-id")

        assert "Hello everyone welcome to class." in result
        assert "Today we discuss capital structure." in result
        assert "Let us begin." in result
        # No timestamps
        assert "-->" not in result
        # No sequence numbers alone
        assert result.strip()[0].isalpha()

    def test_returns_empty_on_empty_srt(self):
        """Input: empty SRT response -- verify empty string returned."""
        client = _make_client(cookie=".ASPXAUTH=abc")
        client._authenticate_cookie()

        mock_resp = _mock_response(text="")
        mock_resp.text = ""

        with patch.object(client._session, "get", return_value=mock_resp):
            result = client._scrape_transcript_from_html("session-id")

        assert result == ""

    def test_strips_auto_generated_disclaimer(self):
        """Lines containing 'Auto-generated transcript' should be omitted."""
        client = _make_client(cookie=".ASPXAUTH=abc")
        client._authenticate_cookie()

        srt_content = (
            "1\n"
            "00:00:00,000 --> 00:00:02,000\n"
            "Auto-generated transcript - may contain errors\n"
            "\n"
            "2\n"
            "00:00:03,000 --> 00:00:05,000\n"
            "Actual lecture content here.\n"
        )
        mock_resp = _mock_response(text=srt_content)
        mock_resp.text = srt_content

        with patch.object(client._session, "get", return_value=mock_resp):
            result = client._scrape_transcript_from_html("session-id")

        assert "Auto-generated" not in result
        assert "Actual lecture content here." in result

    def test_search_sessions_stub_returns_empty(self):
        """search_sessions() should return [] and log a warning (cookie auth limitation)."""
        client = _make_client(cookie=".ASPXAUTH=abc")
        client._authenticate_cookie()

        result = client.search_sessions("FNCE")
        assert result == []
