"""Read-only MCP tools for Union College's Nexus Moodle instance."""

from __future__ import annotations

import io
import json
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
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
MAX_CALENDAR_RANGE = timedelta(days=90)
DISCUSSIONS_PER_PAGE = 20
MAX_DISCUSSION_TEXT_CHARS = 200_000
MAX_DISCUSSION_SUMMARY_CHARS = 2_000
ALLOWED_FILE_PATHS = ("/pluginfile.php/", "/webservice/pluginfile.php/")
READ_ONLY = {"readOnlyHint": True}
_REQUEST_NEXUS_TOKEN: ContextVar[str | None] = ContextVar(
    "request_nexus_token", default=None
)


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


def _parse_datetime(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise NexusError(f"{name} must be a timezone-aware ISO date and time") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NexusError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _shared_mode() -> bool:
    value = os.environ.get("NEXUS_SHARED_MODE", "").strip()
    if value not in {"", "0", "1"}:
        raise NexusError("NEXUS_SHARED_MODE must be 0 or 1")
    return value == "1"


@contextmanager
def _request_credentials(token: str):
    """Bind one student's Nexus token to the current shared-mode request."""
    if not _shared_mode():
        raise NexusError("Request credentials require shared mode")
    token = token.strip()
    if not re.fullmatch(r"[A-Za-z0-9]{16,128}", token):
        raise NexusError("Invalid Nexus request credential")
    marker = _REQUEST_NEXUS_TOKEN.set(token)
    try:
        yield
    finally:
        _REQUEST_NEXUS_TOKEN.reset(marker)


def _credentials() -> tuple[str, str]:
    if _shared_mode():
        if os.environ.get("NEXUS_TOKEN", "").strip() or os.environ.get(
            "NEXUS_CREDENTIAL_FILE", ""
        ).strip():
            raise NexusError("Shared mode refuses owner credentials")
        token = _REQUEST_NEXUS_TOKEN.get()
        if not token:
            raise NexusError("No Nexus credential for this request")
        return SITE, token

    token = os.environ.get("NEXUS_TOKEN", "").strip()
    if token:
        return SITE, token

    from nexus_login import credential_path

    credential_file = credential_path()
    if not credential_file.exists():
        raise NexusError("Sign in with nexus-mcp login or python nexus_login.py")

    try:
        data = json.loads(Path(credential_file).expanduser().read_text())
    except (OSError, json.JSONDecodeError):
        raise NexusError("Could not read Nexus credential file") from None

    if not isinstance(data, dict) or not isinstance(data.get("site", SITE), str):
        raise NexusError("Invalid Nexus credential file")
    if data.get("site", SITE).rstrip("/") != SITE:
        raise NexusError(f"Credential file site must be {SITE}")
    token = data.get("token", "")
    if not isinstance(token, str) or not token.strip():
        raise NexusError("Nexus credential file has no token")
    return SITE, token.strip()


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
    def __init__(self, opener=None, *, token: str | None = None) -> None:  # noqa: ANN001
        self.site, self.token = (SITE, token) if token else _credentials()
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


def _self_user_id(client: MoodleClient) -> int:
    payload = client.call("core_webservice_get_site_info")
    try:
        user_id = int(payload["userid"])
    except (KeyError, TypeError, ValueError):
        raise NexusError("Nexus did not identify the current user") from None
    if user_id <= 0:
        raise NexusError("Nexus did not identify the current user")
    return user_id


def _grade_item(item: dict[str, Any]) -> dict[str, Any]:
    scale_id = item.get("scaleid")
    return {
        "id": item.get("id"),
        "name": item.get("itemname"),
        "item_type": item.get("itemtype"),
        "module": item.get("itemmodule"),
        "instance_id": item.get("iteminstance"),
        "item_number": item.get("itemnumber"),
        "category_id": item.get("categoryid"),
        "outcome_id": item.get("outcomeid"),
        "course_module_id": item.get("cmid"),
        "scale_id": scale_id,
        "is_scale": scale_id not in (None, 0, "0"),
        "weight_raw": item.get("weightraw"),
        "weight_display": item.get("weightformatted"),
        "grade_raw": item.get("graderaw"),
        "grade_display": item.get("gradeformatted"),
        "grade_min": item.get("grademin"),
        "grade_max": item.get("grademax"),
        "range_display": item.get("rangeformatted"),
        "percentage_display": item.get("percentageformatted"),
        "letter_grade_display": item.get("lettergradeformatted"),
        "status": item.get("status"),
        "item_locked": item.get("locked"),
        "submitted_at": _iso(item.get("gradedatesubmitted")),
        "graded_at": _iso(item.get("gradedategraded")),
        "hidden_by_date": item.get("gradehiddenbydate"),
        "needs_update": item.get("gradeneedsupdate"),
        "grade_hidden": item.get("gradeishidden"),
        "grade_locked": item.get("gradeislocked"),
        "grade_overridden": item.get("gradeisoverridden"),
        "rank": item.get("rank"),
        "course_user_count": item.get("numusers"),
        "average_display": item.get("averageformatted"),
        "feedback": _text(item.get("feedback")),
        "feedback_html": item.get("feedback", ""),
    }


def _forum_file_list(item: dict[str, Any]) -> list[dict[str, Any]]:
    files = []
    for key in ("attachments", "messageinlinefiles"):
        for file in item.get(key) or []:
            files.append(_file(file))
    return files


def _discussion_summary(item: dict[str, Any], forum_id: int) -> dict[str, Any]:
    discussion_id = item.get("discussion")
    message = _text(item.get("message"))
    message_html = str(item.get("message") or "")
    message_truncated = len(message) + len(message_html) > MAX_DISCUSSION_SUMMARY_CHARS
    if message_truncated:
        message = message[:MAX_DISCUSSION_SUMMARY_CHARS]
        remaining = MAX_DISCUSSION_SUMMARY_CHARS - len(message)
        message_html = message_html[:remaining] if remaining > 0 else ""
    return {
        "id": discussion_id,
        "first_post_id": item.get("id"),
        "forum_id": forum_id,
        "name": item.get("name") or item.get("subject"),
        "subject": item.get("subject"),
        "message": message,
        "message_html": message_html,
        "message_truncated": message_truncated,
        "author": item.get("userfullname"),
        "created_at": _iso(item.get("created")),
        "modified_at": _iso(item.get("modified") or item.get("timemodified")),
        "opens_at": _iso(item.get("timestart")),
        "closes_at": _iso(item.get("timeend")),
        "reply_count": item.get("numreplies"),
        "unread_count": item.get("numunread"),
        "pinned": item.get("pinned"),
        "locked": item.get("locked"),
        "can_reply": item.get("canreply"),
        "url": f"{SITE}/mod/forum/discuss.php?d={discussion_id}",
        "files": _forum_file_list(item),
    }


def _post(item: dict[str, Any]) -> dict[str, Any]:
    author = item.get("author") or {}
    parent_id = item["parentid"] if "parentid" in item else item.get("parent")
    return {
        "id": item.get("id"),
        "discussion_id": item.get("discussionid") or item.get("discussion"),
        "parent_id": parent_id,
        "subject": item.get("subject") or item.get("replysubject"),
        "message": _text(item.get("message")),
        "message_html": item.get("message", ""),
        "author": author.get("fullname") or item.get("userfullname"),
        "created_at": _iso(item.get("timecreated") or item.get("created")),
        "modified_at": _iso(item.get("timemodified") or item.get("modified")),
        "unread": item.get("unread"),
        "deleted": item.get("isdeleted"),
        "private_reply": item.get("isprivatereply"),
        "files": _forum_file_list(item),
    }


def _bounded_posts(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    posts = []
    used = 0
    truncated = False
    for item in items:
        post = _post(item)
        if used >= MAX_DISCUSSION_TEXT_CHARS:
            truncated = True
            break
        text_keys = ("subject", "message", "message_html")
        for index, key in enumerate(text_keys):
            value = str(post.get(key) or "")
            remaining = MAX_DISCUSSION_TEXT_CHARS - used
            if len(value) > remaining:
                post[key] = value[:remaining]
                post["content_truncated"] = True
                for omitted_key in text_keys[index + 1 :]:
                    post[omitted_key] = ""
                used += remaining
                truncated = True
                break
            else:
                used += len(value)
        posts.append(post)
        if truncated:
            break
    return posts, truncated


mcp = FastMCP(
    "Union Nexus Assignments",
    instructions=(
        "Use list_assignments for native Moodle assignments. Also call course_contents "
        "before concluding a course has no coursework because linked and external activities "
        "may contain tasks. Calendar events, completion, assignments, and grades "
        "are separate signals; do not treat one as proof of another. All tools are read-only."
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
            availability_html = module.get("availabilityinfo") or module.get(
                "availableinfo", ""
            )
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
                    "available_is_inferred": True,
                    "user_visible": module.get("uservisible"),
                    "availability_info": _text(availability_html),
                    "availability_info_html": availability_html,
                    "availability_settings": module.get("availability"),
                    "completion_tracking": module.get("completion"),
                    "completion": module.get("completiondata"),
                    "dates": [
                        {
                            "label": date.get("label"),
                            "at": _iso(date.get("timestamp")),
                            "relative_to": _iso(date.get("relativeto")),
                            "data_id": date.get("dataid"),
                        }
                        for date in module.get("dates", [])
                    ],
                    "contents": [_content(item) for item in module.get("contents", [])],
                }
            )
        section_availability_html = section.get("availabilityinfo", "")
        sections.append(
            {
                "id": section.get("id"),
                "name": section.get("name"),
                "summary": _text(section.get("summary")),
                "summary_html": section.get("summary", ""),
                "visible": section.get("visible"),
                "user_visible": section.get("uservisible"),
                "availability_info": _text(section_availability_html),
                "availability_info_html": section_availability_html,
                "modules": modules,
            }
        )
    return {"course_id": course_id, "sections": sections}


@mcp.tool(annotations=READ_ONLY)
def read_file(url: str) -> dict[str, Any]:
    """Read text or a PDF from a Nexus file URL returned by another tool (10 MB maximum)."""
    return MoodleClient().read_file(url)


@mcp.tool(annotations=READ_ONLY)
def grade_overview() -> dict[str, Any]:
    """List current user's displayed course totals; missing grades stay missing, never zero."""
    client = MoodleClient()
    user_id = _self_user_id(client)
    payload = client.call("gradereport_overview_get_course_grades", userid=user_id)
    course_names = {
        course["id"]: course["name"]
        for course in _courses(client, True)["courses"]
    }
    return {
        "grades": [
            {
                "course_id": grade.get("courseid"),
                "course_name": course_names.get(grade.get("courseid")),
                "grade_display": grade.get("grade"),
                "grade_raw": grade.get("rawgrade"),
                "rank": grade.get("rank"),
                "url": f"{SITE}/grade/report/user/index.php?id={grade.get('courseid')}",
            }
            for grade in payload.get("grades", [])
        ],
        "warnings": payload.get("warnings", []),
        "note": "Values are Moodle's displayed course totals; missing values are not zero and no total is calculated here.",
    }


@mcp.tool(annotations=READ_ONLY)
def course_grades(course_id: int) -> dict[str, Any]:
    """Return current user's visible grade items, categories, feedback, and course total."""
    client = MoodleClient()
    user_id = _self_user_id(client)
    payload = client.call(
        "gradereport_user_get_grade_items", courseid=course_id, userid=user_id
    )
    grade_items = []
    for user_grade in payload.get("usergrades", []):
        if user_grade.get("userid") not in (None, user_id):
            raise NexusError("Nexus returned grades for an unexpected user")
        grade_items.extend(_grade_item(item) for item in user_grade.get("gradeitems", []))
    return {
        "course_id": course_id,
        "grade_items": grade_items,
        "warnings": payload.get("warnings", []),
        "note": "Course totals and displayed grades come from Moodle; ungraded, hidden, and stale states are preserved without calculation.",
    }


@mcp.tool(annotations=READ_ONLY)
def calendar_events(
    start: str, end: str, course_id: int | None = None
) -> dict[str, Any]:
    """List visible calendar events in a timezone-aware ISO interval of at most 90 days."""
    start_at = _parse_datetime(start, "start")
    end_at = _parse_datetime(end, "end")
    if start_at >= end_at:
        raise NexusError("start must be before end")
    if end_at - start_at > MAX_CALENDAR_RANGE:
        raise NexusError("Calendar range cannot exceed 90 days")

    client = MoodleClient()
    params: dict[str, Any] = {
        "options[timestart]": int(start_at.timestamp()),
        "options[timeend]": int(end_at.timestamp()),
        "options[userevents]": course_id is None,
        "options[siteevents]": course_id is None,
        "options[ignorehidden]": True,
    }
    if course_id is not None:
        params["events[courseids][0]"] = course_id
    else:
        for index, course in enumerate(_courses(client, True)["courses"]):
            params[f"events[courseids][{index}]"] = course["id"]
    payload = client.call("core_calendar_get_calendar_events", **params)

    events = []
    seen_ids = set()
    for event in payload.get("events", []):
        if course_id is not None and event.get("courseid") != course_id:
            continue
        event_id = event.get("id")
        if event_id is not None and event_id in seen_ids:
            continue
        if event_id is not None:
            seen_ids.add(event_id)
        try:
            duration = int(event.get("timeduration") or 0)
            end_timestamp = int(event.get("timestart") or 0) + duration
        except (TypeError, ValueError):
            duration = 0
            end_timestamp = 0
        events.append(
            {
                "id": event_id,
                "name": event.get("name"),
                "description": _text(event.get("description")),
                "description_html": event.get("description", ""),
                "starts_at": _iso(event.get("timestart")),
                "ends_at": _iso(end_timestamp) if duration > 0 else None,
                "duration_seconds": duration,
                "event_type": event.get("eventtype"),
                "course_id": event.get("courseid"),
                "category_id": event.get("categoryid"),
                "group_id": event.get("groupid"),
                "user_id": event.get("userid"),
                "repeat_id": event.get("repeatid"),
                "module": event.get("modulename"),
                "instance_id": event.get("instance"),
                "uuid": event.get("uuid"),
                "visible": event.get("visible"),
                "updated_at": _iso(event.get("timemodified")),
                "url": _clean_url(str(event.get("url", "")))
                or f"{SITE}/calendar/view.php?view=day&time={event.get('timestart')}#event_{event_id}",
            }
        )
    return {
        "events": events,
        "warnings": payload.get("warnings", []),
        "query": {
            "start": start_at.isoformat(),
            "end": end_at.isoformat(),
            "course_id": course_id,
        },
        "note": "Group-only events are not included; assignment and quiz tools may contain additional deadlines.",
    }


@mcp.tool(annotations=READ_ONLY)
def list_discussions(
    course_id: int, forum_id: int | None = None, page: int = 0
) -> dict[str, Any]:
    """List visible course forums, or one forum's discussions in pages of 20."""
    if page < 0:
        raise NexusError("page must be zero or greater")
    client = MoodleClient()
    forum_payload = client.call("mod_forum_get_forums_by_courses", courseids=[course_id])
    forums = forum_payload if isinstance(forum_payload, list) else forum_payload.get("forums", [])
    warnings = [] if isinstance(forum_payload, list) else forum_payload.get("warnings", [])

    if forum_id is None:
        return {
            "course_id": course_id,
            "forums": [
                {
                    "id": forum.get("id"),
                    "course_id": forum.get("course"),
                    "name": forum.get("name"),
                    "type": forum.get("type"),
                    "is_announcement": forum.get("type") == "news",
                    "description": _text(forum.get("intro")),
                    "description_html": forum.get("intro", ""),
                    "discussion_count": forum.get("numdiscussions"),
                    "tracked": forum.get("istracked"),
                    "unread_count": forum.get("unreadpostscount"),
                    "rating_assessment_opens_at": _iso(forum.get("assesstimestart")),
                    "rating_assessment_closes_at": _iso(forum.get("assesstimefinish")),
                    "due_at": _iso(forum.get("duedate")),
                    "cutoff_at": _iso(forum.get("cutoffdate")),
                    "url": f"{SITE}/mod/forum/view.php?id={forum.get('cmid') or forum.get('coursemodule')}",
                    "files": [_file(file) for file in forum.get("introfiles", [])],
                }
                for forum in forums
            ],
            "warnings": warnings,
        }

    forum = next(
        (
            item
            for item in forums
            if item.get("id") == forum_id and item.get("course") == course_id
        ),
        None,
    )
    if forum is None:
        raise NexusError("Forum does not belong to course or is unavailable")
    payload = client.call(
        "mod_forum_get_forum_discussions",
        forumid=forum_id,
        page=page,
        perpage=DISCUSSIONS_PER_PAGE,
    )
    discussions = [
        _discussion_summary(item, forum_id)
        for item in payload.get("discussions", [])
    ]
    return {
        "course_id": course_id,
        "forum_id": forum_id,
        "page": page,
        "per_page": DISCUSSIONS_PER_PAGE,
        "discussions": discussions,
        "warnings": warnings + payload.get("warnings", []),
        "next_page": page + 1 if len(discussions) == DISCUSSIONS_PER_PAGE else None,
        "more_may_exist": len(discussions) == DISCUSSIONS_PER_PAGE,
        "summaries_truncated": any(
            discussion["message_truncated"] for discussion in discussions
        ),
    }


@mcp.tool(annotations=READ_ONLY)
def read_discussion(discussion_id: int) -> dict[str, Any]:
    """Read a visible discussion and its replies without marking posts read."""
    payload = MoodleClient().call(
        "mod_forum_get_discussion_posts",
        discussionid=discussion_id,
        sortby="created",
        sortdirection="ASC",
        includeinlineattachments=True,
    )
    source_posts = payload.get("posts", [])
    posts, truncated = _bounded_posts(source_posts)
    return {
        "discussion_id": discussion_id,
        "course_id": payload.get("courseid"),
        "forum_id": payload.get("forumid"),
        "posts": posts,
        "warnings": payload.get("warnings", []),
        "complete": not truncated,
        "truncated": truncated,
        "source_post_count": len(source_posts),
        "returned_post_count": len(posts),
        "omitted_post_count": len(source_posts) - len(posts),
    }


@mcp.tool(annotations=READ_ONLY)
def list_quizzes(course_id: int) -> dict[str, Any]:
    """List visible quiz settings and availability; does not start or inspect attempts."""
    payload = MoodleClient().call("mod_quiz_get_quizzes_by_courses", courseids=[course_id])
    return {
        "course_id": course_id,
        "quizzes": [
            {
                "id": quiz.get("id"),
                "course_id": quiz.get("course"),
                "course_module_id": quiz.get("coursemodule") or quiz.get("cmid"),
                "name": quiz.get("name"),
                "description": _text(quiz.get("intro")),
                "description_html": quiz.get("intro", ""),
                "opens_at": _iso(quiz.get("timeopen")),
                "closes_at": _iso(quiz.get("timeclose")),
                "time_limit_seconds": quiz.get("timelimit"),
                "attempts_allowed": quiz.get("attempts"),
                "grade_method": quiz.get("grademethod"),
                "max_grade": quiz.get("grade"),
                "question_marks_total": quiz.get("sumgrades"),
                "has_questions": quiz.get("hasquestions"),
                "has_feedback": quiz.get("hasfeedback"),
                "completion_requires_pass": quiz.get("completionpass"),
                "overdue_handling": quiz.get("overduehandling"),
                "grace_period_seconds": quiz.get("graceperiod"),
                "url": f"{SITE}/mod/quiz/view.php?id={quiz.get('coursemodule') or quiz.get('cmid')}",
                "files": [_file(file) for file in quiz.get("introfiles", [])],
            }
            for quiz in payload.get("quizzes", [])
        ],
        "warnings": payload.get("warnings", []),
        "note": "Quiz metadata only; attempts and question review are not retrieved.",
    }


if __name__ == "__main__":
    from nexus_login import LoginError, credential_path, login

    if not _shared_mode() and not os.environ.get("NEXUS_TOKEN", "").strip() and not credential_path().exists():
        try:
            login()
        except (LoginError, OSError) as error:
            import sys

            print(str(error) if isinstance(error, LoginError) else "Could not save Nexus sign-in", file=sys.stderr)
            raise SystemExit(1) from None
    mcp.run()
