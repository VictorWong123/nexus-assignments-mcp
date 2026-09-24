# Union Nexus MCP

Read-only MCP server for asking Codex or ChatGPT about Union Nexus courses, assignments, grades, calendar events, discussions, quizzes, course content, and text/PDF attachments.

## Tools

- `list_courses` lists enrolled courses.
- `list_assignments` lists native Moodle assignments and deadlines.
- `assignment_status` returns the current user's submission and grading status.
- `course_contents` lists sections and activities, including access restrictions, activity dates, and completion data.
- `read_file` reads supported Nexus text and PDF attachments.
- `grade_overview` lists Moodle's displayed course totals for the current user.
- `course_grades` lists the current user's visible grade items, categories, status flags, and feedback.
- `calendar_events` lists visible course, personal, and site events in a timezone-aware interval of at most 90 days.
- `list_discussions` lists course forums or a forum's discussions in pages of 20.
- `read_discussion` reads a discussion and its reply tree without marking posts read.
- `list_quizzes` lists quiz availability and settings without starting or inspecting attempts.

## Credentials

Create a Moodle web-service token in Nexus. Keep it outside this directory. The server accepts either:

```sh
export NEXUS_TOKEN='your-token'
```

or a credential file selected with `NEXUS_CREDENTIAL_FILE`:

```json
{"site":"https://nexus.union.edu","token":"your-token"}
```

Restrict the file to your user (`chmod 600 /path/to/credentials.json`) and set its path:

```sh
export NEXUS_CREDENTIAL_FILE=/path/to/credentials.json
```

`NEXUS_TOKEN` takes precedence. Never commit either credential.

## Run locally with Codex

Requires Python 3.10 or newer.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Configure Codex to start `python /absolute/path/to/server.py` as a stdio MCP server and pass one credential environment variable. Then ask, for example: “List every Nexus assignment due in the next two weeks, then read the attached rubrics.”

## Use with ChatGPT

ChatGPT needs a remotely reachable MCP endpoint. Use a managed MCP host that can import the exported `server:mcp` object, store `NEXUS_TOKEN` as a secret, and require authentication before exposing the endpoint. Follow that host's FastMCP 3.2 deployment instructions. Do not publish `python server.py` directly; its default transport is local stdio and this project does not add public HTTP authentication.

## Safety and limits

All 11 tools are read-only and operate as the token's current user. There is no generic Moodle API tool and no submission, upload, enrollment, grading, forum tracking, or quiz-attempt operation. File reads allow only HTTPS URLs on `nexus.union.edu` under Moodle's file paths, refuse redirects, and cap downloads at 10 MB. Text and PDFs are supported; PDF extraction is capped at 50 pages, 500,000 characters, and 8 MB per decompressed stream. Discussion lists return bounded summaries; full discussion text is capped and reports truncation explicitly.

Moodle controls visibility and displayed grade totals. Missing or hidden grades stay missing; the connector does not calculate replacements. `calendar_events` excludes group-only events, so use assignment, quiz, and course-content tools before concluding there are no deadlines. Linked services and external coursework require their own integrations.

Run the focused checks after installing dependencies:

```sh
python -m unittest -v test_server.py
```

## Student login proof (not yet released)

`extension/` is a developer-only Chrome proof for the first release gate: confirming that an ordinary Union student can sign in through the real Nexus/Okta page and obtain the Moodle API access needed by the existing read-only tools without copying a token. It does not connect to the hosted MCP or send a credential anywhere except Nexus.

To run the local proof, open Chrome's Extensions page, enable Developer mode, choose **Load unpacked**, and select the repository's `extension` directory. Click the extension, consent, sign in to Nexus, return to the connection page, and finish the check. Remove the unpacked extension after testing.

The proof may cause Nexus to reuse an existing Moodle mobile-app token or create one if none exists. It never opens the token-management page and never resets a token. Public packaging, managed authentication, credential storage, and the shared MCP deployment remain blocked until this login works for the owner and a second ordinary student account.

Run its dependency-free checks with Node 20 or newer:

```sh
node --test extension/test_login.mjs
```
