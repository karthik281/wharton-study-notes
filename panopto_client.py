"""Panopto API client -- authenticates and fetches session transcripts.

Supports two authentication strategies:
  1. OAuth2 password grant  (PANOPTO_CLIENT_ID + CLIENT_SECRET + USERNAME + PASSWORD)
  2. Cookie-based           (PANOPTO_COOKIE -- copied from browser DevTools)

Penn uses SSO (Azure AD), so the OAuth2 password grant may or may not work
depending on how Penn's Panopto instance is configured. If it fails, fall back
to the cookie method documented in docs/SETUP.md.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger("study_notes.panopto")


class PanoptoAuthError(Exception):
    pass


class PanoptoClient:
    def __init__(
        self,
        server: str,
        client_id: str | None = None,
        client_secret: str | None = None,
        username: str | None = None,
        password: str | None = None,
        cookie: str | None = None,
    ) -> None:
        self._server = server.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._username = username
        self._password = password
        self._cookie = cookie

        self._access_token: str | None = None
        self._token_expiry: float = 0.0

        self._session = requests.Session()
        self._session.headers["Accept"] = "application/json"

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _authenticate_oauth(self) -> None:
        """OAuth2 Resource Owner Password Credentials grant."""
        url = f"https://{self._server}/Panopto/oauth2/connect/token"
        resp = self._session.post(
            url,
            data={
                "grant_type": "password",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "username": self._username,
                "password": self._password,
                "scope": "openid api",
            },
            timeout=15,
        )
        if not resp.ok:
            raise PanoptoAuthError(
                f"OAuth2 password grant failed ({resp.status_code}): {resp.text[:200]}"
            )
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600) - 60
        self._session.headers["Authorization"] = f"Bearer {self._access_token}"
        logger.info("Panopto OAuth2 authentication successful")

    def _authenticate_cookie(self) -> None:
        """Inject browser session cookie directly."""
        self._session.headers["Cookie"] = self._cookie  # type: ignore[assignment]
        logger.info("Panopto cookie authentication configured")

    def authenticate(self) -> None:
        """Choose and execute the appropriate auth strategy."""
        if self._cookie:
            self._authenticate_cookie()
            return
        if self._client_id and self._client_secret and self._username and self._password:
            self._authenticate_oauth()
            return
        raise PanoptoAuthError(
            "No Panopto credentials configured. "
            "Set PANOPTO_CLIENT_ID/SECRET/USERNAME/PASSWORD or PANOPTO_COOKIE in .env"
        )

    def _ensure_auth(self) -> None:
        """Refresh OAuth token if expired. Cookie auth never expires programmatically."""
        if not self._cookie and time.time() >= self._token_expiry:
            self._authenticate_oauth()

    # ------------------------------------------------------------------
    # Session discovery
    # ------------------------------------------------------------------

    def get_all_sessions(self, max_results: int = 20) -> list[dict]:
        """Discover sessions via Data.svc POST endpoint (works with cookie auth).

        Returns a list of dicts with keys: Id (DeliveryID), SessionName, FolderName.
        Results are newest-first. Stops when max_results reached.
        """
        url = f"https://{self._server}/Panopto/Services/Data.svc/GetSessions"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://{self._server}/Panopto/Pages/Sessions/List.aspx",
            "Content-Type": "application/json",
        }

        page_size = min(max_results, 50)
        start_index = 0
        seen_ids: set[str] = set()
        results: list[dict] = []

        while len(results) < max_results:
            body = {
                "queryParameters": {
                    "query": "",
                    "sortColumn": 1,
                    "sortAscending": False,
                    "maxResults": page_size,
                    "startIndex": start_index,
                    "folderID": None,
                    "bookmarked": False,
                    "sessionListOnly": True,
                    "getFolderData": True,
                    "isSharedFolderSearch": False,
                }
            }
            try:
                resp = self._session.post(
                    url, headers=headers, json=body, timeout=20
                )
                resp.raise_for_status()
                data = resp.json()
                page_results = data.get("d", {}).get("Results", [])
                total = data.get("d", {}).get("TotalNumber", 0)
            except requests.RequestException as exc:
                logger.warning("get_all_sessions request failed: %s", exc)
                return results
            except Exception as exc:
                logger.warning("get_all_sessions unexpected error: %s", exc)
                return results

            if not page_results:
                break

            for item in page_results:
                session_id = item.get("DeliveryID") or item.get("Id") or item.get("id")
                if not session_id or session_id in seen_ids:
                    continue
                seen_ids.add(session_id)
                results.append(
                    {
                        "Id": session_id,
                        "SessionName": item.get("SessionName", ""),
                        "FolderName": item.get("FolderName", ""),
                    }
                )
                if len(results) >= max_results:
                    break

            start_index += len(page_results)
            if start_index >= total:
                break

        logger.info("get_all_sessions: returned %d session(s)", len(results))
        return results

    def get_session_info(self, session_id: str) -> dict:
        """Fetch session metadata via DeliveryInfo endpoint (works with cookie auth).

        Returns dict with: Id, SessionName, CourseName, Duration, HasCaptions.
        Falls back to a minimal dict if the request fails.
        """
        try:
            url = (
                f"https://{self._server}/Panopto/Pages/Viewer/DeliveryInfo.aspx"
                f"?deliveryId={session_id}&invocationId=&isLiveNotes=false"
                f"&refreshAuthCookie=true&isActiveBroadcast=false&isEditing=false"
                f"&isKollectiveAgentInstalled=false&isEmbed=false&responseType=json"
            )
            resp = self._session.get(url, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            delivery = data.get("Delivery", {})
            return {
                "Id": session_id,
                "SessionName": delivery.get("SessionName", f"Session {session_id[:8]}"),
                "CourseName": (
                    delivery.get("SessionGroupLongName")
                    or delivery.get("SessionGroupShortName")
                    or "Lectures"
                ),
                "Duration": delivery.get("Duration", 0),
                "HasCaptions": delivery.get("HasCaptions", False),
            }
        except Exception as exc:
            logger.warning("Failed to fetch session info for %s: %s", session_id, exc)
            return {
                "Id": session_id,
                "SessionName": f"Session {session_id[:8]}",
                "CourseName": "Lectures",
            }

    # ------------------------------------------------------------------
    # Transcript
    # ------------------------------------------------------------------

    def get_transcript(self, session_id: str) -> str:
        """Return plain-text transcript for a session, or empty string if unavailable."""
        # Try API first
        try:
            self._ensure_auth()
            url = f"https://{self._server}/Panopto/api/v1/sessions/{session_id}/transcripts/formatted"
            resp = self._session.get(url, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            lines = []
            for transcript in data.get("Transcripts", []):
                for line in transcript.get("Lines", []):
                    text = line.get("Text", "").strip()
                    if text:
                        lines.append(text)
            result = " ".join(lines)
            logger.info(
                "Transcript fetched via API for session %s (%d chars)", session_id, len(result)
            )
            return result
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                logger.info(
                    "API transcript not found (404) -- trying SRT fallback for session %s",
                    session_id,
                )
                # Fall through to SRT fallback
            else:
                logger.warning(
                    "Error fetching transcript via API for %s (status %s): %s",
                    session_id,
                    exc.response.status_code if exc.response else "?",
                    exc,
                )
                return ""
        except Exception as exc:
            logger.warning(
                "Unexpected error fetching transcript via API %s: %s", session_id, exc
            )
            # Fall through to SRT fallback

        # Fallback: SRT endpoint (works with cookie auth)
        try:
            return self._scrape_transcript_from_html(session_id)
        except Exception as exc:
            logger.error("Transcript unavailable for session %s: %s", session_id, exc)
            return ""

    def _scrape_transcript_from_html(self, session_id: str) -> str:
        """Fetch transcript via SRT endpoint (works with cookie auth).

        Endpoint: GET /Panopto/Pages/Transcription/GenerateSRT.ashx?id={id}&language=0
        Strips SRT sequence numbers and timestamps, returns plain text.
        """
        url = (
            f"https://{self._server}/Panopto/Pages/Transcription/"
            f"GenerateSRT.ashx?id={session_id}&language=0"
        )
        try:
            resp = self._session.get(url, timeout=30)
            resp.raise_for_status()
            srt = resp.text.strip()
            if not srt:
                logger.warning("SRT transcript empty for session %s", session_id)
                return ""

            # Parse SRT format: strip sequence numbers, timestamps, keep only text
            lines = []
            for line in srt.splitlines():
                line = line.strip()
                # Skip empty lines, sequence numbers, and timestamp lines
                if not line:
                    continue
                if line.isdigit():
                    continue
                if "-->" in line:
                    continue
                # Skip the auto-generated disclaimer
                if "Auto-generated transcript" in line:
                    continue
                lines.append(line)

            result = " ".join(lines)
            logger.info(
                "SRT transcript fetched for session %s (%d chars)", session_id, len(result)
            )
            return result
        except Exception as exc:
            logger.warning("Failed to fetch SRT transcript for %s: %s", session_id, exc)
            return ""

    # ------------------------------------------------------------------
    # Session search (stub -- does not work with cookie auth)
    # ------------------------------------------------------------------

    def search_sessions(self, query: str, max_results: int = 5) -> list[dict]:
        """Search sessions by name -- NOT supported with cookie auth.

        Use get_all_sessions() instead.
        """
        logger.warning(
            "search_sessions is not supported with cookie auth. "
            "Use get_all_sessions() to discover sessions."
        )
        return []
