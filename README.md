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

ChatGPT needs a remotely reachable MCP endpoint. A host configured with `NEXUS_TOKEN` is private and single-account only; never share that endpoint with another student. A multi-user deployment must set `NEXUS_SHARED_MODE=1`, configure neither `NEXUS_TOKEN` nor `NEXUS_CREDENTIAL_FILE`, and add authenticated middleware that supplies the correct request-scoped credential. This repository does not include that hosted authentication yet. Do not publish `python server.py` directly; its default transport is local stdio.

## Safety and limits

All 11 tools are read-only and operate as the token's current user. There is no generic Moodle API tool and no submission, upload, enrollment, grading, forum tracking, or quiz-attempt operation. File reads allow only HTTPS URLs on `nexus.union.edu` under Moodle's file paths, refuse redirects, and cap downloads at 10 MB. Text and PDFs are supported; PDF extraction is capped at 50 pages, 500,000 characters, and 8 MB per decompressed stream. Discussion lists return bounded summaries; full discussion text is capped and reports truncation explicitly.

Moodle controls visibility and displayed grade totals. Missing or hidden grades stay missing; the connector does not calculate replacements. `calendar_events` excludes group-only events, so use assignment, quiz, and course-content tools before concluding there are no deadlines. Linked services and external coursework require their own integrations.

Run the focused checks after installing dependencies:

```sh
python -m unittest -v test_server.py
```

## Student login proof (not yet released)

`extension/` is a developer-only Chrome proof for the first release gate: confirming that an ordinary Union student can sign in through the real Nexus/Okta page and obtain the Moodle API access needed by the existing read-only tools without copying a token. It does not connect to the hosted MCP or send a credential anywhere except Nexus.

The owner-account live proof passed on September 23, 2026: Nexus/Okta login completed, the returned credential matched the one-time passport, the fixed Nexus API returned the authenticated student identity, and all 12 functions required by the 11 tools were available (453 functions total). This proves the login handoff for one account only. Cross-account isolation has synthetic concurrency coverage; a second live student account remains a public-release verification gate.

To run the local proof, open Chrome's Extensions page, enable Developer mode, choose **Load unpacked**, and select the repository's `extension` directory. Click the extension, consent, sign in to Nexus, return to the connection page, and finish the check. Remove the unpacked extension after testing.

The proof may cause Nexus to reuse an existing Moodle mobile-app token or create one if none exists. It never opens the token-management page and never resets a token. Multi-user development can proceed, but public packaging remains blocked until a second ordinary student verifies the complete flow.

Run its dependency-free checks with Node 20 or newer:

```sh
node --test extension/test_*.mjs
```

## Shared-mode credential seam

`NEXUS_SHARED_MODE=1` makes the server require a request-scoped Nexus credential. In this mode it refuses `NEXUS_TOKEN` and `NEXUS_CREDENTIAL_FILE`, and a request without its own credential fails closed. Personal stdio mode is unchanged when shared mode is unset or `0`.

This is an internal prerequisite for authenticated hosting, not a complete hosted setup. The shared HTTP entry point validates OAuth access tokens, but no credential vault is wired yet; future request middleware must retrieve only that student's vaulted Nexus token and bind it with `_request_credentials` for the duration of one request.

`shared_server:app` is the stateless HTTP entry point deployed at `https://union-nexus-mcp.vercel.app/mcp`. It validates Descope tokens against the configured issuer and JWKS, requires that exact audience and the `nexus:read` scope, and refuses to start outside shared mode or with owner credentials configured. It does not yet retrieve a student's Nexus credential, so authenticated tool calls that need Nexus remain intentionally unavailable until the server-only credential contract is configured and reviewed.
