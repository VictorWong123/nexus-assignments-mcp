"""Opt-in real Chromium tests; all SSO responses are synthetic and intercepted."""
import base64
import hashlib
import json
import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

import nexus_login


@unittest.skipUnless(os.environ.get("NEXUS_TEST_BROWSER"), "Set NEXUS_TEST_BROWSER to a Chromium executable")
class BrowserLoginTest(unittest.TestCase):
    def run_flow(self, mode):
        from playwright.sync_api import sync_playwright

        visits, browsers, failures = [], [], []

        @contextmanager
        def fixture_runtime():
            with sync_playwright() as runtime:
                def launch(**_kwargs):
                    browser = runtime.chromium.launch(executable_path=os.environ["NEXUS_TEST_BROWSER"], headless=True)
                    browsers.append(browser)
                    original_context = browser.new_context

                    def new_context():
                        context = original_context()
                        context.on("requestfailed", lambda request: failures.append(request.failure))

                        def route_request(route):
                            url = route.request.url
                            parts = urlsplit(url)
                            visits.append(parts.hostname)
                            query = parse_qs(parts.query)
                            if parts.hostname == "union.okta.com":
                                route.fulfill(content_type="text/html", body="<script>location.href=" + json.dumps(query["return"][0]) + ";</script>")
                            elif nexus_login._is_launch_page(url):
                                if "fixture_signed_in" not in query:
                                    location = "https://union.okta.com/fixture-login?" + urlencode({"return": url + "&fixture_signed_in=1"})
                                    # Use a fresh navigation so Playwright intercepts every
                                    # fixture request instead of following a fulfilled 302 outside routing.
                                    route.fulfill(content_type="text/html", body="<script>location.href=" + json.dumps(location) + ";</script>")
                                    return
                                passport = query["passport"][0] if mode != "wrong_passport" else "different-attempt"
                                binding = hashlib.md5((nexus_login.SITE + passport).encode()).hexdigest()
                                payload = base64.b64encode(f"{binding}:::{'a' * 32}:::discard-private".encode()).decode()
                                callback = "openlms://token=" + payload
                                duplicate = f'<a id="launchapp" href="{callback}">Duplicate</a>' if mode == "ambiguous" else ""
                                route.fulfill(content_type="text/html", body=f'<a id="launchapp" href="{callback}">Open</a>{duplicate}<script>document.getElementById("launchapp").click();</script>')
                            else:
                                route.abort()

                        context.route("**/*", route_request)
                        return context

                    browser.new_context = new_context
                    return browser

                yield SimpleNamespace(chromium=SimpleNamespace(launch=launch))

        with patch("playwright.sync_api.sync_playwright", fixture_runtime), patch("nexus_login.LOGIN_TIMEOUT", 5):
            try:
                token = nexus_login.browser_token()
            except nexus_login.LoginError as error:
                if mode not in {"wrong_passport", "ambiguous"}:
                    raise AssertionError(f"Synthetic flow failed after visits {visits}, failures {failures}: {error}") from error
                raise
            finally:
                self.assertTrue(browsers)
                self.assertFalse(browsers[0].is_connected())
        self.assertIn("union.okta.com", visits)
        self.assertIn("nexus.union.edu", visits)
        return token

    def test_html_handoff_after_sso(self):
        self.assertEqual(self.run_flow("html"), "a" * 32)

    def test_ambiguous_handoff_is_rejected_after_sso(self):
        with self.assertRaisesRegex(nexus_login.LoginError, "unsupported app callback"):
            self.run_flow("ambiguous")

    def test_wrong_passport_is_rejected_after_sso(self):
        with self.assertRaisesRegex(nexus_login.LoginError, "did not match"):
            self.run_flow("wrong_passport")


if __name__ == "__main__":
    unittest.main()
