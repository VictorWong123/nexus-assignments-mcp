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

## Browser sign-in (local desktop clients)

The server can open a separate browser window for Union's normal Nexus/Okta sign-in, including MFA. It uses Moodle's existing mobile-app SSO handoff to obtain a credential automatically; users do not paste a token or give their password to the MCP. This requires Nexus to enable the `moodle_mobile_app` web service and mobile browser SSO. The existing Chrome extension proof records a successful owner-account login on September 23, 2026; the new desktop launcher has not yet been tested with a live Union account.

For an npm install from this checkout, with Node 18+ and Python 3.10+ installed:

```sh
npm install -g .
nexus-mcp login
```

The launcher installs the Python dependencies into its own user cache on first run. Sign-in uses installed Chrome or Edge, or Playwright Chromium. If neither browser is available, run `nexus-mcp install-browser` first. This package is not published to the npm registry.

Configure a desktop MCP client with:

```json
{"mcpServers":{"nexus":{"command":"nexus-mcp"}}}
```

Starting `nexus-mcp` without a saved credential also opens sign-in automatically. Run `nexus-mcp login` before adding the client configuration so the first dependency install does not hit your client's connection timeout. Login/setup messages go to stderr so they do not corrupt the stdio MCP connection. Running `nexus-mcp login` again replaces the saved credential only after Nexus confirms the signed-in user and the 12 API functions required by the tools. If a credential expires or is revoked, run login again.

The credential is stored at `~/.config/nexus-mcp/credentials.json` by default, or at `NEXUS_CREDENTIAL_FILE` if configured. On POSIX systems, new credential files are restricted to the current user (`0600`). The login browser context is temporary; the app does not retain Okta cookies, passwords, or Moodle's optional private token. A desktop display is required. This is browser-assisted Moodle SSO, not a new Okta OAuth application.

The launch URL requests Moodle's confirmation page. The launcher reads the `launchapp` link directly from that page's response before Moodle's automatic native-app navigation can replace it. Branded callbacks such as `openlms://` are accepted only as an inert credential envelope with the correct Nexus/one-time-passport binding; browser and executable URL schemes are rejected.

### Verification status — October 19, 2026

- A packaged npm tarball installed into a clean prefix; its launcher installed Python dependencies and completed MCP initialization and discovery of all 11 tools using a synthetic credential. No student data was requested.
- Real headless Chromium exercised an intercepted, synthetic Nexus → Okta → Nexus flow, including the auto-clicking Moodle confirmation page, branded callback parsing, mismatched-passport rejection, ambiguous-link rejection, and browser cleanup. All fixture responses were supplied by the test; this was not a real Okta sign-in.
- Python checks cover the existing tools, saved credentials, required API permissions, and shared-server isolation. The existing extension checks remain intact.
- This cloud environment has no desktop display or Union login credentials. A live login through the new desktop launcher and a second ordinary student's account remain unverified. The earlier owner-account extension proof is recorded below. The package remains private/unpublished, and no hosted deployment was changed.

To repeat the browser fixtures after installing `requirements-login.txt`, set the path to an installed Chromium executable:

```sh
NEXUS_TEST_BROWSER=/usr/bin/chromium python -m unittest -v test_browser_login.py
```

## Existing token credentials

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

Configure Codex to start `python /absolute/path/to/server.py` as a stdio MCP server. To use browser sign-in with this Python installation, install `requirements-login.txt` instead of `requirements.txt`, and run `python nexus_login.py` once. Chrome or Edge must be installed; alternatively run `python -m playwright install chromium`. Existing credential environment variables also work. Then ask, for example: “List every Nexus assignment due in the next two weeks, then read the attached rubrics.”

## Use with ChatGPT

The new desktop browser login does not complete ChatGPT enrollment. The existing hosted MCP has a Descope OAuth authentication boundary, but the per-user Nexus credential enrollment and vault connection remain unfinished.

Moodle's mobile handoff supplies a native app callback rather than an HTTPS OAuth callback. The desktop launcher captures that handoff inside its own login browser. It does not send credentials to the hosted MCP. The developer extension below proves a separate browser-based handoff that can inform future enrollment work.

A host configured with `NEXUS_TOKEN` is private and single-account only. Multi-user deployments must use `NEXUS_SHARED_MODE=1` with authenticated request-scoped credentials, never a saved desktop credential. Do not expose the stdio server publicly or share one student's credentials with other students.

## Safety and limits

All 11 tools are read-only and operate as the token's current user. There is no generic Moodle API tool and no submission, upload, enrollment, grading, forum tracking, or quiz-attempt operation. File reads allow only HTTPS URLs on `nexus.union.edu` under Moodle's file paths, refuse redirects, and cap downloads at 10 MB. Text and PDFs are supported; PDF extraction is capped at 50 pages, 500,000 characters, and 8 MB per decompressed stream. Discussion lists return bounded summaries; full discussion text is capped and reports truncation explicitly.

Moodle controls visibility and displayed grade totals. Missing or hidden grades stay missing; the connector does not calculate replacements. `calendar_events` excludes group-only events, so use assignment, quiz, and course-content tools before concluding there are no deadlines. Linked services and external coursework require their own integrations.

Run the focused checks after installing dependencies:

```sh
python -m unittest -v test_server.py test_login.py test_shared_server.py
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
