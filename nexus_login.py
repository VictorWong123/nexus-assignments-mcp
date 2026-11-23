"""Interactive Moodle mobile SSO; passwords stay in the Union login window."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlsplit

SITE = "https://nexus.union.edu"
LAUNCH_PATH = "/admin/tool/mobile/launch.php"
LOGIN_TIMEOUT = 300
BLOCKED_CALLBACK_SCHEMES = {
    "about", "chrome", "chrome-extension", "data", "devtools", "file",
    "http", "https", "javascript", "view-source",
}
MAX_LAUNCH_HTML_CHARS = 1_000_000
REQUIRED_FUNCTIONS = {
    "core_calendar_get_calendar_events", "core_course_get_contents",
    "core_course_get_enrolled_courses_by_timeline_classification",
    "core_webservice_get_site_info", "gradereport_overview_get_course_grades",
    "gradereport_user_get_grade_items", "mod_assign_get_assignments",
    "mod_assign_get_submission_status", "mod_forum_get_discussion_posts",
    "mod_forum_get_forum_discussions", "mod_forum_get_forums_by_courses",
    "mod_quiz_get_quizzes_by_courses",
}


class _LaunchLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and attributes.get("id") == "launchapp":
            self.links.append(attributes.get("href") or "")


class LoginError(RuntimeError):
    """An error safe to display without exposing the browser response."""


def credential_path() -> Path:
    selected = os.environ.get("NEXUS_CREDENTIAL_FILE", "").strip()
    if selected:
        return Path(selected).expanduser()
    return Path.home() / ".config" / "nexus-mcp" / "credentials.json"


def decode_callback(callback: str, passport: str) -> str:
    """Validate Moodle's site/passport binding before accepting its token."""
    if len(callback) > 8192:
        raise LoginError("Nexus returned an invalid sign-in response")
    prefix = re.match(r"([A-Za-z][A-Za-z0-9+.-]{0,63})://token=", callback)
    if not prefix or prefix[1].lower() in BLOCKED_CALLBACK_SCHEMES:
        raise LoginError("Nexus returned an unsupported app callback")
    try:
        fields = base64.b64decode(callback[prefix.end():], validate=True).decode().split(":::")
    except (ValueError, UnicodeError):
        raise LoginError("Nexus returned an invalid sign-in response") from None
    expected = hashlib.md5((SITE + passport).encode()).hexdigest()  # Moodle's protocol, not password hashing.
    if len(fields) not in (2, 3) or not secrets.compare_digest(fields[0], expected):
        raise LoginError("Nexus sign-in response did not match this login attempt")
    token = fields[1]
    if not re.fullmatch(r"[A-Za-z0-9]{16,128}", token):
        raise LoginError("Nexus returned an invalid credential")
    return token  # Never retain the optional Moodle private token.


def save_credentials(token: str) -> None:
    path = credential_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            os.chmod(temporary, 0o600)
            json.dump({"site": SITE, "token": token}, output)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _is_launch_page(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc == "nexus.union.edu" and parts.path == LAUNCH_PATH


def browser_token() -> str:
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        raise LoginError(
            "Browser sign-in needs login dependencies. Install requirements-login.txt, "
            "then run python -m playwright install chromium."
        ) from None

    passport = secrets.token_urlsafe(32)
    launch_url = SITE + LAUNCH_PATH + "?" + urlencode({
        "service": "moodle_mobile_app", "passport": passport, "urlscheme": "moodlemobile",
        "confirmed": "1",
    })
    callbacks: list[str] = []

    def response_received(response):
        # Only Moodle's own launch endpoint can supply a credential callback.
        if _is_launch_page(response.url):
            location = response.headers.get("location", "")
            if re.match(r"[A-Za-z][A-Za-z0-9+.-]{0,63}://token=", location):
                callbacks.append(location)
            elif "text/html" in response.headers.get("content-type", ""):
                # Moodle auto-clicks its native link on load. Capture the response
                # before that navigation can replace the page with a browser error.
                try:
                    html = response.text()
                except Error:
                    return
                if len(html) <= MAX_LAUNCH_HTML_CHARS:
                    parser = _LaunchLinks()
                    parser.feed(html)
                    if len(parser.links) == 1:
                        callbacks.append(parser.links[0])
                    elif parser.links:
                        callbacks.append("ambiguous-response")

    with sync_playwright() as playwright:
        browser = None
        # Prefer an existing desktop browser; use Playwright Chromium otherwise.
        for channel in ("chrome", "msedge", None):
            try:
                browser = playwright.chromium.launch(headless=False, channel=channel)
                break
            except Error:
                continue
        if browser is None:
            raise LoginError(
                "Could not open a sign-in window. Use a desktop session and install "
                "Chrome, Edge, or run python -m playwright install chromium."
            )
        try:
            context = browser.new_context()  # Ephemeral; never persist Okta cookies or passwords.
            context.on("response", response_received)
            page = context.new_page()
            print("Sign in to Nexus in the browser window, including any Union MFA.", file=sys.stderr)
            try:
                page.goto(launch_url, wait_until="domcontentloaded", timeout=30_000)
            except Error:
                pass  # A custom-scheme redirect can report a navigation error after success.
            deadline = time.monotonic() + LOGIN_TIMEOUT
            while time.monotonic() < deadline:
                if callbacks:
                    return decode_callback(callbacks[0], passport)
                if not context.pages:
                    raise LoginError("Nexus sign-in window was closed")
                for candidate in context.pages:
                    if _is_launch_page(candidate.url):
                        try:
                            link = candidate.locator("a#launchapp").get_attribute("href", timeout=100)
                            if link:
                                return decode_callback(link, passport)
                        except Error:
                            pass
                try:
                    context.pages[0].wait_for_timeout(200)
                except Error:
                    raise LoginError("Nexus sign-in window was closed") from None
            raise LoginError(
                "Nexus sign-in timed out. This requires Nexus to enable Moodle mobile "
                "browser SSO and the mobile web service. No login settings were changed."
            )
        finally:
            browser.close()


def login() -> None:
    from server import MoodleClient, NexusError, _shared_mode

    if _shared_mode():
        raise LoginError("Desktop sign-in is unavailable in shared server mode")

    token = browser_token()
    try:
        # Check the returned credential before replacing a working saved login.
        info = MoodleClient(token=token).call("core_webservice_get_site_info")
        if (
            not isinstance(info, dict)
            or type(info.get("userid")) is not int
            or info["userid"] <= 0
            or not isinstance(info.get("siteurl"), str)
            or info.get("siteurl", "").rstrip("/") != SITE
        ):
            raise LoginError("Nexus did not confirm the signed-in user")
        functions = info.get("functions")
        if not isinstance(functions, list):
            raise LoginError("Nexus did not confirm the available APIs")
        available = {
            item["name"] for item in functions
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        if not REQUIRED_FUNCTIONS.issubset(available):
            raise LoginError("Nexus sign-in did not grant the APIs required by this MCP")
    except NexusError:
        raise LoginError("Nexus could not validate the sign-in credential") from None
    save_credentials(token)
    print("Connected to Nexus. You can close the sign-in window.", file=sys.stderr)


if __name__ == "__main__":
    try:
        login()
    except (LoginError, OSError) as error:
        # OSError can include file paths; never dump a browser or network exception.
        print(str(error) if isinstance(error, LoginError) else "Could not save Nexus sign-in", file=sys.stderr)
        raise SystemExit(1) from None
