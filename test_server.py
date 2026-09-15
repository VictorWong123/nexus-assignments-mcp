import json
import os
import unittest
from unittest.mock import patch

import server
from server import (
    MoodleClient,
    NexusError,
    _NoRedirects,
    _assignments,
    _bounded_posts,
    _content,
    _courses,
)


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


class _FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def call(self, function, **params):
        self.calls.append((function, params))
        expected_function, response = self.responses.pop(0)
        if function != expected_function:
            raise AssertionError(f"Expected {expected_function}, got {function}")
        return response


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

    def test_course_grades_preserves_zero_scale_and_visibility_states(self):
        client = _FakeClient(
            [
                ("core_webservice_get_site_info", {"userid": 42}),
                (
                    "gradereport_user_get_grade_items",
                    {
                        "usergrades": [
                            {
                                "userid": 42,
                                "gradeitems": [
                                    {
                                        "id": 1,
                                        "itemname": "Quiz",
                                        "itemtype": "mod",
                                        "scaleid": 0,
                                        "graderaw": 0.0,
                                        "gradeformatted": "0.00",
                                        "gradeishidden": False,
                                        "gradeneedsupdate": True,
                                        "feedback": "<p>Try again</p>",
                                    },
                                    {
                                        "id": 2,
                                        "itemname": "Participation",
                                        "itemtype": "category",
                                        "scaleid": 7,
                                        "graderaw": None,
                                        "gradeformatted": "Excellent",
                                        "gradeishidden": True,
                                    },
                                    {
                                        "id": 3,
                                        "itemname": "Course total",
                                        "itemtype": "course",
                                        "scaleid": 0,
                                        "graderaw": 0.0,
                                        "locked": True,
                                        "gradeislocked": True,
                                        "gradeisoverridden": True,
                                    },
                                ],
                            }
                        ],
                        "warnings": [],
                    },
                ),
            ]
        )
        with patch.object(server, "MoodleClient", return_value=client):
            result = server.course_grades(9)

        self.assertEqual(result["grade_items"][0]["grade_raw"], 0.0)
        self.assertTrue(result["grade_items"][0]["needs_update"])
        self.assertEqual(result["grade_items"][0]["feedback"], "Try again")
        self.assertIsNone(result["grade_items"][1]["grade_raw"])
        self.assertTrue(result["grade_items"][1]["is_scale"])
        self.assertTrue(result["grade_items"][1]["grade_hidden"])
        self.assertEqual(result["grade_items"][2]["item_type"], "course")
        self.assertTrue(result["grade_items"][2]["grade_locked"])
        self.assertTrue(result["grade_items"][2]["grade_overridden"])
        self.assertEqual(client.calls[1][1]["userid"], 42)

    def test_course_grades_rejects_another_users_data(self):
        client = _FakeClient(
            [
                ("core_webservice_get_site_info", {"userid": 42}),
                (
                    "gradereport_user_get_grade_items",
                    {"usergrades": [{"userid": 99, "gradeitems": []}]},
                ),
            ]
        )
        with patch.object(server, "MoodleClient", return_value=client):
            with self.assertRaisesRegex(NexusError, "unexpected user"):
                server.course_grades(9)

    def test_grade_overview_joins_course_names_without_inventing_grade(self):
        client = _FakeClient(
            [
                ("core_webservice_get_site_info", {"userid": 42}),
                (
                    "gradereport_overview_get_course_grades",
                    {
                        "grades": [
                            {"courseid": 9, "grade": "-", "rawgrade": None}
                        ],
                        "warnings": [],
                    },
                ),
                (
                    "core_course_get_enrolled_courses_by_timeline_classification",
                    {
                        "courses": [{"id": 9, "fullname": "CSC 321"}],
                        "nextoffset": 20,
                    },
                ),
                (
                    "core_course_get_enrolled_courses_by_timeline_classification",
                    {"courses": [], "nextoffset": 40},
                ),
            ]
        )
        with patch.object(server, "MoodleClient", return_value=client):
            result = server.grade_overview()

        self.assertEqual(result["grades"][0]["course_name"], "CSC 321")
        self.assertIsNone(result["grades"][0]["grade_raw"])
        self.assertEqual(client.calls[1][1], {"userid": 42})

    def test_calendar_requires_timezone_order_and_bounded_range(self):
        bad_ranges = [
            ("2026-09-01T00:00:00", "2026-09-02T00:00:00", "timezone"),
            (
                "2026-09-02T00:00:00+00:00",
                "2026-09-01T00:00:00+00:00",
                "before",
            ),
            (
                "2026-01-01T00:00:00+00:00",
                "2026-04-02T00:00:00+00:00",
                "90 days",
            ),
        ]
        for start, end, message in bad_ranges:
            with self.subTest(message=message):
                with self.assertRaisesRegex(NexusError, message):
                    server.calendar_events(start, end)

    def test_calendar_uses_nested_parameters_filters_and_deduplicates_ids(self):
        event = {
            "id": 3,
            "name": "Due",
            "description": "<p>Submit</p>",
            "timestart": 1_780_000_000,
            "timeduration": 3600,
            "eventtype": "due",
            "courseid": 9,
        }
        client = _FakeClient(
            [
                (
                    "core_calendar_get_calendar_events",
                    {"events": [event, event], "warnings": []},
                )
            ]
        )
        with patch.object(server, "MoodleClient", return_value=client):
            result = server.calendar_events(
                "2026-09-01T00:00:00-04:00",
                "2026-09-02T00:00:00-04:00",
                9,
            )

        params = client.calls[0][1]
        self.assertEqual(params["events[courseids][0]"], 9)
        self.assertIn("options[timestart]", params)
        self.assertIn("options[timeend]", params)
        self.assertTrue(params["options[ignorehidden]"])
        self.assertFalse(params["options[userevents]"])
        self.assertFalse(params["options[siteevents]"])
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["description"], "Submit")
        self.assertIn("calendar/view.php", result["events"][0]["url"])
        self.assertEqual(result["query"]["start"], "2026-09-01T04:00:00+00:00")

    def test_calendar_without_course_includes_all_enrolled_course_ids(self):
        client = _FakeClient(
            [
                (
                    "core_course_get_enrolled_courses_by_timeline_classification",
                    {
                        "courses": [
                            {"id": 9, "fullname": "One"},
                            {"id": 10, "fullname": "Two"},
                        ],
                        "nextoffset": None,
                    },
                ),
                ("core_calendar_get_calendar_events", {"events": [], "warnings": []}),
            ]
        )
        with patch.object(server, "MoodleClient", return_value=client):
            server.calendar_events(
                "2026-09-01T00:00:00+00:00", "2026-09-02T00:00:00+00:00"
            )
        params = client.calls[1][1]
        self.assertEqual(params["events[courseids][0]"], 9)
        self.assertEqual(params["events[courseids][1]"], 10)
        self.assertTrue(params["options[userevents]"])
        self.assertTrue(params["options[siteevents]"])

    def test_forums_and_discussions_preserve_pagination_and_actual_id(self):
        forum = {
            "id": 12,
            "course": 9,
            "type": "news",
            "name": "Announcements",
            "intro": "<p>Updates</p>",
            "numdiscussions": 1,
            "cmid": 44,
        }
        client = _FakeClient(
            [("mod_forum_get_forums_by_courses", [forum])]
        )
        with patch.object(server, "MoodleClient", return_value=client):
            forums = server.list_discussions(9)
        self.assertTrue(forums["forums"][0]["is_announcement"])
        self.assertEqual(forums["forums"][0]["description"], "Updates")

        discussions = [
            {
                "id": 100 + index,
                "discussion": 500 + index,
                "subject": f"Post {index}",
            }
            for index in range(20)
        ]
        client = _FakeClient(
            [
                ("mod_forum_get_forums_by_courses", [forum]),
                (
                    "mod_forum_get_forum_discussions",
                    {"discussions": discussions, "warnings": []},
                ),
            ]
        )
        with patch.object(server, "MoodleClient", return_value=client):
            result = server.list_discussions(9, 12, 2)
        self.assertEqual(result["discussions"][0]["id"], 500)
        self.assertEqual(result["discussions"][0]["first_post_id"], 100)
        self.assertEqual(result["next_page"], 3)
        self.assertEqual(client.calls[1][1]["perpage"], 20)

    def test_forum_must_belong_to_course(self):
        client = _FakeClient(
            [("mod_forum_get_forums_by_courses", [{"id": 12, "course": 8}])]
        )
        with patch.object(server, "MoodleClient", return_value=client):
            with self.assertRaisesRegex(NexusError, "does not belong"):
                server.list_discussions(9, 99)
        self.assertEqual(len(client.calls), 1)

    def test_discussion_summaries_report_text_truncation(self):
        forum = {"id": 12, "course": 9}
        client = _FakeClient(
            [
                ("mod_forum_get_forums_by_courses", [forum]),
                (
                    "mod_forum_get_forum_discussions",
                    {
                        "discussions": [
                            {"id": 1, "discussion": 5, "message": "long message"}
                        ],
                        "warnings": [{"warningcode": "partial"}],
                    },
                ),
            ]
        )
        with patch.object(server, "MAX_DISCUSSION_SUMMARY_CHARS", 5):
            with patch.object(server, "MoodleClient", return_value=client):
                result = server.list_discussions(9, 12)
        self.assertTrue(result["summaries_truncated"])
        self.assertTrue(result["discussions"][0]["message_truncated"])
        self.assertLessEqual(len(result["discussions"][0]["message"]), 5)
        self.assertEqual(result["warnings"], [{"warningcode": "partial"}])

    def test_discussion_preserves_reply_tree_and_reports_truncation(self):
        posts = [
            {
                "id": 1,
                "discussionid": 5,
                "parentid": 0,
                "subject": "Root",
                "message": "abcdefghij",
                "author": {"fullname": "Professor"},
            },
            {
                "id": 2,
                "discussionid": 5,
                "parentid": 1,
                "message": "reply",
            },
        ]
        client = _FakeClient(
            [
                (
                    "mod_forum_get_discussion_posts",
                    {"posts": posts, "courseid": 9, "forumid": 12, "warnings": []},
                )
            ]
        )
        with patch.object(server, "MAX_DISCUSSION_TEXT_CHARS", 10):
            with patch.object(server, "MoodleClient", return_value=client):
                result = server.read_discussion(5)
        self.assertFalse(result["complete"])
        self.assertTrue(result["truncated"])
        self.assertTrue(result["posts"][0]["content_truncated"])
        self.assertEqual(result["omitted_post_count"], 1)
        self.assertEqual(client.calls[0][1]["sortdirection"], "ASC")
        self.assertNotIn("marksread", client.calls[0][1])

        mapped, truncated = _bounded_posts(posts)
        self.assertFalse(truncated)
        self.assertEqual(mapped[0]["parent_id"], 0)
        self.assertEqual(mapped[1]["parent_id"], 1)

    def test_quizzes_handle_populated_and_empty_results(self):
        quiz = {
            "id": 7,
            "course": 9,
            "coursemodule": 55,
            "name": "Quiz 1",
            "intro": "<p>Chapter 1</p>",
            "timeopen": 0,
            "timeclose": 0,
            "timelimit": 600,
            "attempts": 2,
        }
        client = _FakeClient(
            [
                (
                    "mod_quiz_get_quizzes_by_courses",
                    {"quizzes": [quiz], "warnings": []},
                )
            ]
        )
        with patch.object(server, "MoodleClient", return_value=client):
            result = server.list_quizzes(9)
        self.assertIsNone(result["quizzes"][0]["opens_at"])
        self.assertIsNone(result["quizzes"][0]["closes_at"])
        self.assertEqual(result["quizzes"][0]["time_limit_seconds"], 600)

        client = _FakeClient(
            [
                (
                    "mod_quiz_get_quizzes_by_courses",
                    {"quizzes": [], "warnings": []},
                )
            ]
        )
        with patch.object(server, "MoodleClient", return_value=client):
            self.assertEqual(server.list_quizzes(9)["quizzes"], [])

    def test_course_contents_adds_access_completion_and_dates(self):
        payload = [
            {
                "id": 2,
                "name": "Week 1",
                "summary": "<p>Start</p>",
                "visible": 1,
                "uservisible": True,
                "modules": [
                    {
                        "id": 4,
                        "name": "Assignment",
                        "modname": "assign",
                        "description": "<p>Do work</p>",
                        "url": "https://nexus.union.edu/mod/assign/view.php?id=4",
                        "visible": 1,
                        "uservisible": False,
                        "availabilityinfo": "<p>Opens Friday</p>",
                        "completion": 2,
                        "completiondata": {"state": 0, "timecompleted": 0},
                        "dates": [{"label": "Due", "timestamp": 1_780_000_000}],
                        "contents": [],
                    }
                ],
            }
        ]
        client = _FakeClient([("core_course_get_contents", payload)])
        with patch.object(server, "MoodleClient", return_value=client):
            result = server.course_contents(9)
        module = result["sections"][0]["modules"][0]
        self.assertEqual(module["id"], 4)
        self.assertEqual(module["description"], "Do work")
        self.assertTrue(module["available"])
        self.assertTrue(module["available_is_inferred"])
        self.assertFalse(module["user_visible"])
        self.assertEqual(module["availability_info"], "Opens Friday")
        self.assertEqual(module["completion"], {"state": 0, "timecompleted": 0})
        self.assertIsNotNone(module["dates"][0]["at"])

    def test_new_tools_only_call_read_only_data_functions(self):
        clients = [
            _FakeClient(
                [
                    ("core_webservice_get_site_info", {"userid": 42}),
                    ("gradereport_overview_get_course_grades", {"grades": []}),
                    (
                        "core_course_get_enrolled_courses_by_timeline_classification",
                        {"courses": []},
                    ),
                ]
            ),
            _FakeClient(
                [
                    ("core_webservice_get_site_info", {"userid": 42}),
                    ("gradereport_user_get_grade_items", {"usergrades": []}),
                ]
            ),
            _FakeClient(
                [
                    (
                        "core_course_get_enrolled_courses_by_timeline_classification",
                        {"courses": []},
                    ),
                    ("core_calendar_get_calendar_events", {"events": []}),
                ]
            ),
            _FakeClient([("mod_forum_get_forums_by_courses", [])]),
            _FakeClient(
                [
                    (
                        "mod_forum_get_discussion_posts",
                        {"posts": [], "courseid": 9, "forumid": 12},
                    )
                ]
            ),
            _FakeClient([("mod_quiz_get_quizzes_by_courses", {"quizzes": []})]),
        ]
        with patch.object(server, "MoodleClient", side_effect=clients):
            server.grade_overview()
            server.course_grades(9)
            server.calendar_events(
                "2026-09-01T00:00:00+00:00", "2026-09-02T00:00:00+00:00"
            )
            server.list_discussions(9)
            server.read_discussion(5)
            server.list_quizzes(9)
        functions = [function for client in clients for function, _ in client.calls]
        allowed = {
            "core_webservice_get_site_info",
            "gradereport_overview_get_course_grades",
            "gradereport_user_get_grade_items",
            "core_course_get_enrolled_courses_by_timeline_classification",
            "core_calendar_get_calendar_events",
            "mod_forum_get_forums_by_courses",
            "mod_forum_get_discussion_posts",
            "mod_quiz_get_quizzes_by_courses",
        }
        self.assertLessEqual(set(functions), allowed)


if __name__ == "__main__":
    unittest.main()
