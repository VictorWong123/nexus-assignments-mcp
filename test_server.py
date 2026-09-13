import json
import os
import unittest
from unittest.mock import patch

from server import MoodleClient, NexusError, _NoRedirects, _assignments, _content, _courses


class _Headers(dict):
    def get_content_type(self):
        return self.get("Content-Type", "application/octet-stream").split(";", 1)[0]


class _Response:
    def __init__(self, body, content_type="application/json"):
        self.body = body
        self.headers = _Headers({"Content-Type": content_type})

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, _limit):
        return self.body


class _Opener:
    def __init__(self, response):
        self.response = response
        self.request = None

    def open(self, request, timeout):
        self.request = request
        return self.response


class _PagedClient:
    def __init__(self):
        self.offsets = []

    def call(self, _function, **params):
        self.offsets.append(params["offset"])
        if params["offset"] == 0:
            return {"courses": [{"id": 1, "fullname": "First"}], "nextoffset": 20}
        return {"courses": [], "nextoffset": 40}


class NexusServerTest(unittest.TestCase):
    def client(self, body=b"{}", content_type="application/json"):
        env = patch.dict(os.environ, {"NEXUS_TOKEN": "top-secret-token"}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        return MoodleClient(_Opener(_Response(body, content_type)))

    def test_rejects_non_nexus_file_url(self):
        with self.assertRaisesRegex(NexusError, "must be a Nexus"):
            self.client().read_file("https://example.com/pluginfile.php/steal.txt")

    def test_redirects_are_rejected(self):
        with self.assertRaisesRegex(NexusError, "redirected"):
            _NoRedirects().redirect_request(
                None, None, 302, "Found", {}, "https://example.com"
            )

    def test_file_read_uses_webservice_route_and_redacts_output(self):
        client = self.client(b"token=top-secret-token", "text/plain")
        result = client.read_file(
            "https://nexus.union.edu/pluginfile.php/1/file.txt?forcedownload=1&token=old"
        )
        self.assertIn("/webservice/pluginfile.php/", client.opener.request.full_url)
        self.assertNotIn("token=old", result["url"])
        self.assertNotIn("top-secret-token", result["content"])

    def test_course_pagination_stops_on_empty_page(self):
        client = _PagedClient()
        self.assertEqual(
            [course["id"] for course in _courses(client, False)["courses"]], [1]
        )
        self.assertEqual(client.offsets, [0, 20])

    def test_inline_course_content_is_preserved(self):
        result = _content(
            {"type": "content", "content": '<p>Read <a href="/spec">spec</a></p>'}
        )
        self.assertEqual(result["content"], "Read spec")
        self.assertIn('href="/spec"', result["content_html"])

    def test_assignment_warnings_are_preserved(self):
        payload = {
            "courses": [{"id": 7, "fullname": "Course", "assignments": []}],
            "warnings": [{"warningcode": "notice", "message": "Partial result"}],
        }
        result = _assignments(self.client(json.dumps(payload).encode()), None)
        self.assertEqual(result["warnings"], payload["warnings"])

    def test_api_error_does_not_leak_token(self):
        payload = {
            "exception": "moodle_exception",
            "message": "Rejected token top-secret-token; token=top-secret-token",
        }
        with self.assertRaises(NexusError) as raised:
            self.client(json.dumps(payload).encode()).call("example")
        self.assertNotIn("top-secret-token", str(raised.exception))
        self.assertIn("[REDACTED]", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
