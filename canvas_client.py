"""Canvas API client — fetches courses, modules, files, and Panopto links."""

import logging
import re
from pathlib import Path

import requests
from canvasapi import Canvas
from canvasapi.course import Course
from canvasapi.module import Module, ModuleItem

logger = logging.getLogger("study_notes.canvas")

# Regex to extract a Panopto session UUID from any URL or iframe src
_PANOPTO_ID_RE = re.compile(
    r"[?&]id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)


class CanvasClient:
    def __init__(self, base_url: str, api_token: str) -> None:
        self._canvas = Canvas(base_url, api_token)
        self._token = api_token
        self._base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Courses
    # ------------------------------------------------------------------

    def get_active_courses(self) -> list[Course]:
        """Return courses the user is enrolled in this term."""
        user = self._canvas.get_current_user()
        courses = list(
            user.get_courses(
                enrollment_state="active",
                enrollment_type="student",
                include=["term", "total_students"],
            )
        )
        logger.info("Found %d active course(s)", len(courses))
        return courses

    # ------------------------------------------------------------------
    # Modules
    # ------------------------------------------------------------------

    def get_all_modules(self, course: Course) -> list[Module]:
        """Return all published modules for a course, in Canvas order."""
        try:
            modules = [m for m in course.get_modules() if getattr(m, "published", True)]
            return modules
        except Exception as exc:
            logger.warning("Could not fetch modules for %s: %s", course.name, exc)
            return []

    def get_latest_module(self, course: Course) -> Module | None:
        """Return the last module in the list (most recent session)."""
        modules = self.get_all_modules(course)
        if not modules:
            return None
        latest = modules[-1]
        logger.info(
            "Latest module for '%s': '%s'",
            getattr(course, "name", course.id),
            getattr(latest, "name", latest.id),
        )
        return latest

    def get_module_items(self, module: Module) -> list[ModuleItem]:
        """Return all items inside a module."""
        try:
            return list(module.get_module_items(include=["content_details"]))
        except Exception as exc:
            logger.warning("Could not fetch items for module %s: %s", module.id, exc)
            return []

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    def download_file(self, file_url: str, filename: str, dest_dir: Path) -> Path | None:
        """Download a file from Canvas and save to dest_dir."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        if dest.exists():
            logger.debug("Already exists, skipping: %s", dest.name)
            return dest
        try:
            headers = {"Authorization": f"Bearer {self._token}"}
            resp = requests.get(file_url, headers=headers, timeout=60, stream=True)
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=8192):
                    fh.write(chunk)
            logger.info("Downloaded: %s", dest.name)
            return dest
        except Exception as exc:
            logger.warning("Failed to download %s: %s", filename, exc)
            return None

    def download_module_item_file(
        self, item: ModuleItem, dest_dir: Path
    ) -> Path | None:
        """Download the file attached to a File-type module item."""
        if getattr(item, "type", "") != "File":
            return None
        try:
            content = getattr(item, "content_details", {}) or {}
            url = content.get("url") or getattr(item, "url", None)
            name = content.get("display_name") or getattr(item, "title", f"file_{item.id}")
            if not url:
                # Construct from file ID
                file_id = getattr(item, "content_id", None)
                if not file_id:
                    return None
                url = f"{self._base_url}/api/v1/files/{file_id}/download"
            return self.download_file(url, name, dest_dir)
        except Exception as exc:
            logger.warning("Could not resolve file item %s: %s", item.id, exc)
            return None

    # ------------------------------------------------------------------
    # Panopto session ID extraction
    # ------------------------------------------------------------------

    def extract_panopto_id(self, item: ModuleItem) -> str | None:
        """Extract a Panopto session UUID from a module item URL or page body."""
        # ExternalTool items often have the session ID in their URL
        url = getattr(item, "url", "") or getattr(item, "external_url", "") or ""
        match = _PANOPTO_ID_RE.search(url)
        if match:
            return match.group(1)
        return None

    def extract_panopto_id_from_html(self, html: str) -> str | None:
        """Extract a Panopto session UUID embedded in page HTML."""
        match = _PANOPTO_ID_RE.search(html)
        return match.group(1) if match else None

    def get_page_html(self, course: Course, page_url: str) -> str:
        """Fetch the body HTML of a Canvas wiki page."""
        try:
            slug = page_url.split("/")[-1]
            page = course.get_page(slug)
            return getattr(page, "body", "") or ""
        except Exception as exc:
            logger.warning("Could not fetch page %s: %s", page_url, exc)
            return ""

    def collect_panopto_ids(
        self, course: Course, items: list[ModuleItem]
    ) -> list[str]:
        """Scan all module items and return any Panopto session IDs found."""
        ids = []
        for item in items:
            # Direct URL match
            pid = self.extract_panopto_id(item)
            if pid:
                ids.append(pid)
                continue
            # Dive into Page body
            if getattr(item, "type", "") == "Page":
                html = self.get_page_html(course, getattr(item, "page_url", ""))
                pid = self.extract_panopto_id_from_html(html)
                if pid:
                    ids.append(pid)
        return list(dict.fromkeys(ids))  # deduplicate while preserving order
