import base64
import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import nexus_login
import server


def callback(passport="attempt", token="a" * 32, private=""):
    binding = hashlib.md5((nexus_login.SITE + passport).encode()).hexdigest()
    payload = f"{binding}:::{token}" + (f":::{private}" if private else "")
    return "nexusmcp://token=" + base64.b64encode(payload.encode()).decode()


class LoginTest(unittest.TestCase):
    def test_callback_matches_attempt_and_discards_private_token(self):
        self.assertEqual(nexus_login.decode_callback(callback(private="private-secret"), "attempt"), "a" * 32)

    def test_rejects_wrong_attempt_or_origin_binding(self):
        with self.assertRaises(nexus_login.LoginError):
            nexus_login.decode_callback(callback("other-attempt"), "attempt")

    def test_rejects_invalid_payload_without_exposing_it(self):
        for value in ("https://evil.test/token=secret", "nexusmcp://token=secret!", "nexusmcp://wrong=secret", callback(token="")):
            with self.subTest(value=value), self.assertRaises(nexus_login.LoginError) as raised:
                nexus_login.decode_callback(value, "attempt")
            self.assertNotIn("secret", str(raised.exception))

    def test_accepts_standard_mobile_scheme(self):
        self.assertEqual(nexus_login.decode_callback(callback().replace("nexusmcp:", "moodlemobile:"), "attempt"), "a" * 32)

    def test_branded_schemes_and_unsafe_schemes(self):
        self.assertEqual(nexus_login.decode_callback(callback().replace("nexusmcp:", "openlms:"), "attempt"), "a" * 32)
        for scheme in nexus_login.BLOCKED_CALLBACK_SCHEMES:
            with self.subTest(scheme=scheme), self.assertRaises(nexus_login.LoginError):
                nexus_login.decode_callback(callback().replace("nexusmcp:", scheme + ":"), "attempt")

    def test_shared_mode_never_opens_desktop_login_or_reads_cache(self):
        with patch.dict(os.environ, {"NEXUS_SHARED_MODE": "1"}, clear=True), patch("nexus_login.browser_token") as browser, patch("nexus_login.credential_path") as cache:
            with self.assertRaises(nexus_login.LoginError):
                nexus_login.login()
            with self.assertRaises(server.NexusError):
                server._credentials()
            browser.assert_not_called()
            cache.assert_not_called()

    def test_only_nexus_launch_page_can_provide_callback(self):
        self.assertTrue(nexus_login._is_launch_page(nexus_login.SITE + nexus_login.LAUNCH_PATH + "?service=test"))
        for url in ("https://evil.test" + nexus_login.LAUNCH_PATH, "https://nexus.union.edu.evil.test" + nexus_login.LAUNCH_PATH, "http://nexus.union.edu" + nexus_login.LAUNCH_PATH, nexus_login.SITE + "/login/index.php"):
            self.assertFalse(nexus_login._is_launch_page(url))

    def test_save_private_file_and_read_without_environment_token(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "credentials.json"
            with patch.dict(os.environ, {"NEXUS_CREDENTIAL_FILE": str(path)}, clear=True):
                nexus_login.save_credentials("a" * 32)
                self.assertEqual(server._credentials(), (nexus_login.SITE, "a" * 32))
                self.assertEqual(json.loads(path.read_text()), {"site": nexus_login.SITE, "token": "a" * 32})
                if os.name != "nt":
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_default_cache_is_used_and_environment_token_still_wins(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True), patch("pathlib.Path.home", return_value=Path(folder)):
            nexus_login.save_credentials("saved-token")
            self.assertEqual(server._credentials()[1], "saved-token")
            with patch.dict(os.environ, {"NEXUS_TOKEN": "explicit-token"}):
                self.assertEqual(server._credentials()[1], "explicit-token")

    def test_failed_validation_preserves_previous_login(self):
        with patch("nexus_login.browser_token", return_value="b" * 32), patch("server.MoodleClient") as client, patch("nexus_login.save_credentials") as save:
            client.return_value.call.side_effect = server.NexusError("private upstream details")
            with self.assertRaises(nexus_login.LoginError) as raised:
                nexus_login.login()
            self.assertNotIn("private upstream", str(raised.exception))
            save.assert_not_called()

    def test_success_validates_user_before_saving(self):
        with patch("nexus_login.browser_token", return_value="b" * 32), patch("server.MoodleClient") as client, patch("nexus_login.save_credentials") as save:
            client.return_value.call.return_value = {
                "userid": 42, "siteurl": nexus_login.SITE,
                "functions": [{"name": name} for name in nexus_login.REQUIRED_FUNCTIONS],
            }
            nexus_login.login()
            client.assert_called_once_with(token="b" * 32)
            save.assert_called_once_with("b" * 32)

    def test_missing_moodle_permissions_preserves_previous_login(self):
        with patch("nexus_login.browser_token", return_value="b" * 32), patch("server.MoodleClient") as client, patch("nexus_login.save_credentials") as save:
            client.return_value.call.return_value = {"userid": 42, "siteurl": nexus_login.SITE, "functions": []}
            with self.assertRaisesRegex(nexus_login.LoginError, "required by this MCP"):
                nexus_login.login()
            save.assert_not_called()

    def test_browser_receives_moodle_redirect_and_always_closes(self):
        for valid_attempt in (True, False):
            with self.subTest(valid_attempt=valid_attempt):
                browser = MagicMock()
                context = browser.new_context.return_value
                page = context.new_page.return_value
                context.pages = [page]

                def navigate(url, **_kwargs):
                    passport = parse_qs(urlsplit(url).query)["passport"][0]
                    response = SimpleNamespace(
                        url=url,
                        headers={"location": callback(passport if valid_attempt else "wrong-attempt")},
                    )
                    context.on.call_args.args[1](response)

                page.goto.side_effect = navigate
                runtime = MagicMock()
                runtime.__enter__.return_value.chromium.launch.return_value = browser
                fake_module = SimpleNamespace(Error=RuntimeError, sync_playwright=lambda: runtime)
                with patch.dict(sys.modules, {"playwright.sync_api": fake_module}):
                    if valid_attempt:
                        self.assertEqual(nexus_login.browser_token(), "a" * 32)
                    else:
                        with self.assertRaises(nexus_login.LoginError):
                            nexus_login.browser_token()
                browser.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
