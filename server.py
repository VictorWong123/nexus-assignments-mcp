"""Read-only MCP tools for Union College's Nexus Moodle instance."""

from __future__ import annotations

import io
import json
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastmcp import FastMCP
from pypdf import PdfReader, apply_configuration

SITE = "https://nexus.union.edu"
API_URL = f"{SITE}/webservice/rest/server.php"
REQUEST_TIMEOUT_SECONDS = 30
MAX_API_RESPONSE_BYTES = 25 * 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 50
MAX_PDF_TEXT_CHARS = 500_000
MAX_PDF_STREAM_BYTES = 8 * 1024 * 1024
ALLOWED_FILE_PATHS = ("/pluginfile.php/", "/webservice/pluginfile.php/")
READ_ONLY = {"readOnlyHint": True}


class NexusError(RuntimeError):
    """Safe error returned to MCP clients."""


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise NexusError("Nexus redirected a request; stopped to protect credentials")


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _text(value: Any) -> str:
    parser = _HTMLText()
    parser.feed(str(value or ""))
    return " ".join(" ".join(parser.parts).split())


def _iso(timestamp: Any) -> str | None:
    try:
        value = int(timestamp)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value > 0 else None


def _credentials() -> tuple[str, str]:
    token = os.environ.get("NEXUS_TOKEN", "").strip()
    if token:
        return SITE, token

    credential_file = os.environ.get("NEXUS_CREDENTIAL_FILE", "").strip()
    if not credential_file:
        raise NexusError("Set NEXUS_TOKEN or NEXUS_CREDENTIAL_FILE")

    try:
        data = json.loads(Path(credential_file).expanduser().read_text())
    except (OSError, json.JSONDecodeError):
        raise NexusError("Could not read Nexus credential file") from None

    if data.get("site", SITE).rstrip("/") != SITE:
        raise NexusError(f"Credential file site must be {SITE}")
    token = str(data.get("token", "")).strip()
    if not token:
        raise NexusError("Nexus credential file has no token")
    return SITE, token


def _redact(value: str, token: str) -> str:
    value = value.replace(token, "[REDACTED]") if token else value
    return re.sub(r"(?i)(wstoken|token)=[^&\s]+", r"\1=[REDACTED]", value)


def _sanitize(value: Any, token: str) -> Any:
    if isinstance(value, str):
        return _redact(value, token)
    if isinstance(value, list):
        return [_sanitize(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize(item, token) for key, item in value.items()}
    return value


def _clean_url(value: str) -> str:
    parts = urlsplit(value)
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in {"token", "wstoken"}
        ]
    )
    fragment = re.sub(
        r"(?i)(wstoken|token)=[^&\s]+", r"\1=[REDACTED]", parts.fragment
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, fragment))


class MoodleClient:
    def __init__(self, opener=None) -> None:  # noqa: ANN001
        self.site, self.token = _credentials()
        self.opener = opener or build_opener(_NoRedirects())

    def call(self, function: str, **params: Any) -> Any:
        form: list[tuple[str, Any]] = [
            ("wstoken", self.token),
            ("wsfunction", function),
            ("moodlewsrestformat", "json"),
        ]
        for key, value in params.items():
            if isinstance(value, (list, tuple)):
                form.extend((f"{key}[{index}]", item) for index, item in enumerate(value))
            elif value is not None:
                form.append((key, int(value) if isinstance(value, bool) else value))

        request = Request(
            API_URL,
            data=urlencode(form).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                body = response.read(MAX_API_RESPONSE_BYTES + 1)
        except NexusError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError):
            raise NexusError("Nexus request failed") from None

        if len(body) > MAX_API_RESPONSE_BYTES:
            raise NexusError("Nexus response exceeded size limit")
        try:
            result = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise NexusError("Nexus returned an invalid response") from None
        if isinstance(result, dict) and result.get("exception"):
            message = result.get("message") or result.get("errorcode") or "API error"
            raise NexusError(_redact(f"Nexus API error: {message}", self.token)) from None
        return _sanitize(result, self.token)

    def read_file(self, url: str) -> dict[str, Any]:
        clean_url = _clean_url(url)
        parts = urlsplit(clean_url)
        try:
            valid_port = parts.port in (None, 443)
        except ValueError:
            valid_port = False
        if (
            parts.scheme != "https"
            or parts.hostname != "nexus.union.edu"
            or not valid_port
            or parts.username is not None
            or not parts.path.startswith(ALLOWED_FILE_PATHS)
        ):
            raise NexusError("File URL must be a Nexus Moodle file URL")

        query = parse_qsl(parts.query, keep_blank_values=True)
        query.append(("token", self.token))
        path = parts.path
        if path.startswith("/pluginfile.php/"):
            path = f"/webservice{path}"
        authenticated_url = urlunsplit(
            (parts.scheme, parts.netloc, path, urlencode(query), "")
        )
        request = Request(authenticated_url, headers={"Accept": "*/*"})
        try:
            with self.opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                declared_size = int(response.headers.get("Content-Length", "0") or 0)
                if declared_size > MAX_FILE_BYTES:
                    raise NexusError("File exceeds 10 MB limit")
                content_type = response.headers.get_content_type().lower()
                data = response.read(MAX_FILE_BYTES + 1)
        except NexusError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            raise NexusError("Nexus file request failed") from None

        if len(data) > MAX_FILE_BYTES:
            raise NexusError("File exceeds 10 MB limit")
        if content_type == "application/pdf" or parts.path.lower().endswith(".pdf"):
            try:
                with apply_configuration(
                    maximum_declared_stream_length=MAX_PDF_STREAM_BYTES,
                    array_based_stream_maximum_output_length=MAX_PDF_STREAM_BYTES,
                    jbig2_maximum_output_length=MAX_PDF_STREAM_BYTES,
                    lzw_maximum_output_length=MAX_PDF_STREAM_BYTES,
                    run_length_maximum_output_length=MAX_PDF_STREAM_BYTES,
                    zlib_maximum_output_length=MAX_PDF_STREAM_BYTES,
                    image_maximum_buffer_size=MAX_PDF_STREAM_BYTES,
                    page_tree_maximum_entries=MAX_PDF_PAGES,
                ):
                    reader = PdfReader(io.BytesIO(data))
                    if len(reader.pages) > MAX_PDF_PAGES:
                        raise NexusError("PDF exceeds 50-page limit")
                    extracted = []
                    extracted_chars = 0
                    for page in reader.pages:
                        page_text = page.extract_text() or ""
                        extracted_chars += len(page_text)
                        if extracted_chars > MAX_PDF_TEXT_CHARS:
                            raise NexusError("PDF extracted text exceeds size limit")
                        extracted.append(page_text)
                    content = "\n\n".join(extracted)
            except NexusError:
                raise
            except Exception:
                raise NexusError("Could not read PDF") from None
            kind = "pdf"
            warning = (
                None
                if content.strip()
                else "PDF has no extractable text; it may be scanned and require OCR."
            )
        elif content_type.startswith("text/") or content_type in {
            "application/json",
            "application/xml",
            "application/xhtml+xml",
        }:
            content = data.decode("utf-8", errors="replace")
            kind = "text"
            warning = None
        else:
            raise NexusError(f"Unsupported file type: {content_type or 'unknown'}")
        return {
            "url": clean_url,
            "type": kind,
            "content": _redact(content, self.token),
            "warning": warning,
        }


def _file(file: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": file.get("filename"),
        "url": _clean_url(str(file.get("fileurl", ""))),
        "mime_type": file.get("mimetype"),
        "size": file.get("filesize"),
    }


def _content(item: dict[str, Any]) -> dict[str, Any]:
    content = _file(item)
    content["type"] = item.get("type", "file")
    if item.get("content") is not None:
        content["content"] = _text(item["content"])
        content["content_html"] = item["content"]
    return content


def _assignments(client: MoodleClient, course_ids: list[int] | None) -> dict[str, Any]:
    payload = client.call("mod_assign_get_assignments", courseids=course_ids or None)
    assignments = []
    for course in payload.get("courses", []):
        for assignment in course.get("assignments", []):
            attachments = (assignment.get("introfiles") or []) + (
                assignment.get("introattachments") or []
            )
            assignments.append(
                {
                    "id": assignment.get("id"),
                    "course_id": course.get("id") or assignment.get("course"),
                    "course_name": course.get("fullname") or course.get("shortname"),
                    "name": assignment.get("name"),
                    "instructions": _text(assignment.get("intro")),
                    "instructions_html": assignment.get("intro", ""),
                    "due_at": _iso(assignment.get("duedate")),
                    "opens_at": _iso(assignment.get("allowsubmissionsfromdate")),
                    "cutoff_at": _iso(assignment.get("cutoffdate")),
                    "grading_due_at": _iso(assignment.get("gradingduedate")),
                    "updated_at": _iso(assignment.get("timemodified")),
                    "url": f"{SITE}/mod/assign/view.php?id={assignment.get('cmid')}",
                    "files": [_file(item) for item in attachments],
                    "grade_max": assignment.get("grade"),
                    "grading_method": assignment.get("gradingmethod"),
                    "team_submission": bool(assignment.get("teamsubmission")),
                }
            )
    return {
        "assignments": assignments,
        "warnings": payload.get("warnings", []),
        "note": "Native Moodle assignments only; inspect course_contents for linked or external coursework.",
    }


def _courses(client: MoodleClient, include_all: bool) -> dict[str, Any]:
    classification = "all" if include_all else "inprogress"
    offset = 0
    courses = []
    seen_offsets: set[int] = set()
    while offset not in seen_offsets:
        seen_offsets.add(offset)
        payload = client.call(
            "core_course_get_enrolled_courses_by_timeline_classification",
            classification=classification,
            offset=offset,
        )
        page = payload.get("courses", [])
        if not page:
            break
        courses.extend(page)
        next_offset = payload.get("nextoffset")
        if next_offset is None:
            break
        offset = int(next_offset)

    return {
        "courses": [
            {
                "id": course.get("id"),
                "name": course.get("fullname"),
                "short_name": course.get("shortname"),
                "start_at": _iso(course.get("startdate")),
                "end_at": _iso(course.get("enddate")),
                "url": f"{SITE}/course/view.php?id={course.get('id')}",
            }
            for course in courses
        ],
        "classification": classification,
        "note": "Moodle timeline classification may include community or older courses; use course dates and names.",
    }


mcp = FastMCP(
    "Union Nexus Assignments",
    instructions=(
        "Use list_assignments for native Moodle assignments. Also call course_contents "
        "before concluding a course has no coursework because linked and external activities "
        "may contain tasks. All tools are read-only."
    ),
)


@mcp.tool(annotations=READ_ONLY)
def list_courses(include_all: bool = False) -> dict[str, Any]:
    """List enrolled Nexus courses. Set include_all for past and future courses."""
    return _courses(MoodleClient(), include_all)


@mcp.tool(annotations=READ_ONLY)
def list_assignments(course_ids: list[int] | None = None) -> dict[str, Any]:
    """List assignments without dropping undated or historical items; optionally filter by course IDs."""
    return _assignments(MoodleClient(), course_ids)


@mcp.tool(annotations=READ_ONLY)
def assignment_status(assignment_id: int) -> dict[str, Any]:
    """Return current user's submission and grading status for one assignment."""
    return MoodleClient().call("mod_assign_get_submission_status", assignid=assignment_id)


@mcp.tool(annotations=READ_ONLY)
def course_contents(course_id: int) -> dict[str, Any]:
    """List sections, activities, pages, resources, and file links in a course."""
    payload = MoodleClient().call("core_course_get_contents", courseid=course_id)
    sections = []
    for section in payload:
        modules = []
        for module in section.get("modules", []):
            modules.append(
                {
                    "id": module.get("id"),
                    "name": module.get("name"),
                    "type": module.get("modname"),
                    "description": _text(module.get("description")),
                    "description_html": module.get("description", ""),
                    "url": _clean_url(str(module.get("url", ""))),
                    "visible": module.get("visible"),
                    "available": module.get("availableinfo") in (None, ""),
                    "contents": [_content(item) for item in module.get("contents", [])],
                }
            )
        sections.append(
            {
                "id": section.get("id"),
                "name": section.get("name"),
                "summary": _text(section.get("summary")),
                "modules": modules,
            }
        )
    return {"course_id": course_id, "sections": sections}


@mcp.tool(annotations=READ_ONLY)
def read_file(url: str) -> dict[str, Any]:
    """Read text or a PDF from a Nexus file URL returned by another tool (10 MB maximum)."""
    return MoodleClient().read_file(url)


if __name__ == "__main__":
    mcp.run()
