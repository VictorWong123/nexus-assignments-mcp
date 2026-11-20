# Union Nexus MCP

Connect a local desktop MCP client to your Union Nexus account. Ask about your courses, assignments, deadlines, grades, discussions, quizzes, and course attachments. All 11 tools are read-only.

**Start here:** install the npm launcher from GitHub, run `nexus-mcp login`, and sign in through Union's normal Nexus/Okta page with your Union email/account and MFA. You do not need to find or paste a Moodle token, and the MCP does not ask for your password in the terminal.

This is a local desktop preview. The npm package is unpublished (`private: true`); install from the `feature/browser-sign-in` branch, which contains the launcher. The repository's `main` branch still has the older token-only setup. The desktop launcher has synthetic install/login checks, but a live Union sign-in through this launcher and a second student's account remain unverified. See [verification and release status](RELEASE.md).

## 1. Install

You need:

- Node.js 18 or newer with npm.
- Python 3.10 or newer with `venv` and pip support, available as `python3` or `python`.
- Git for the GitHub install.
- A desktop session and Chrome or Edge, or the Chromium install below.
- Your own Union account with Nexus access and an internet connection.

Run in a terminal:

```sh
npm install -g "git+https://github.com/VictorWong123/nexus-assignments-mcp.git#feature/browser-sign-in"
nexus-mcp --help
```

Do not use `npm install -g nexus-assignments-mcp`: there is no published registry release. If GitHub requests authentication, you need access to the repository.

Alternatively, install from a source checkout:

```sh
git clone --branch feature/browser-sign-in https://github.com/VictorWong123/nexus-assignments-mcp.git
cd nexus-assignments-mcp
npm install -g .
```

## 2. Sign in with your Union account

```sh
nexus-mcp login
```

The first run creates a Python environment under `~/.cache/nexus-mcp/` and downloads the required Python packages. You do not need to run pip yourself for the npm install.

1. Wait for the separate browser window to open.
2. Sign in on Union's Nexus/Okta page with your usual Union email/account, password, and MFA. Enter credentials only in that browser window.
3. Complete any Nexus mobile-app confirmation shown during the handoff.
4. Wait for the terminal to report `Connected to Nexus. You can close the sign-in window.` The login browser closes automatically.

If Chrome and Edge are unavailable, install the fallback browser, then retry:

```sh
nexus-mcp install-browser
nexus-mcp login
```

Finish this login before configuring your MCP client so the initial dependency download does not exhaust the client's startup timeout. Starting `nexus-mcp` without a saved credential also opens login automatically.

## 3. Connect your MCP client

### Codex

If the Codex CLI is installed, register the local server:

```sh
codex mcp add nexus -- nexus-mcp
```

Restart or reconnect your client after adding the server. If you already have a Nexus server configured with `server.py` and a manually supplied token, replace that entry with the launcher and remove its old credential environment variables.

### Other local desktop MCP clients

For clients that accept an `mcpServers` JSON configuration, add this entry to the existing configuration:

```json
{
  "mcpServers": {
    "nexus": {
      "command": "nexus-mcp"
    }
  }
}
```

Use the client's equivalent settings if it has a different format. This is a local stdio server: the command is `nexus-mcp`, with no arguments, URL, password, or token field. The client must run as the same operating-system user who completed login.

If a desktop app cannot find the command, run `command -v nexus-mcp` on macOS/Linux or `where.exe nexus-mcp` on Windows and use the returned executable's absolute path in the command setting.

### Check the connection

Ask your client:

> List my Nexus courses.

Then try:

> Find all coursework due in the next two weeks. Check assignments, calendar events, quizzes, and linked course activities, and read any attached rubrics.

A working connection exposes the 11 tools below and returns your account's courses. External course services need their own integrations.

## Sign in again, switch accounts, or remove access

Run `nexus-mcp login` again if the credential expires, is revoked, or you want to switch Union accounts. A successful login replaces the saved credential only after Nexus validates the account and all 12 API functions required by the tools. Restart or reconnect the MCP client afterward.

The credential is saved at `~/.config/nexus-mcp/credentials.json` by default, including on Windows under your user home directory. `NEXUS_CREDENTIAL_FILE` can select another path; set the same value when logging in and when starting the MCP client. New credential files use `0600` permissions on POSIX systems. Keep this file private and out of Git, chat messages, and shared folders.

To remove local access, disconnect the server in your MCP client and delete that credential file. There is no `logout` subcommand; starting the launcher again without a credential starts a new login. Deleting the local file does not revoke the credential at Nexus. Use Nexus's account/token controls if you need server-side revocation; revoking a reused mobile-app token can also affect your Moodle mobile app.

To uninstall the npm launcher:

```sh
npm uninstall -g nexus-assignments-mcp
```

Uninstalling leaves the saved credential, cached Python environment, and any downloaded Playwright browser in place. Delete the saved credential separately to remove local access.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| `nexus-mcp` is not found | Check the npm global executable directory is on PATH, reopen the terminal, or use the executable's absolute path in your client. |
| npm reports a global install permission error | Use a Node installation or npm prefix writable by your user, then retry. |
| Setup asks for Python or fails downloading packages | Confirm `python3` or `python` is Python 3.10+, has `venv`/pip, and can download the packages in `requirements-login.txt`. |
| No sign-in browser opens | Run in a desktop session with Chrome or Edge installed, or run `nexus-mcp install-browser`. |
| Sign-in times out | Retry `nexus-mcp login` and complete MFA within five minutes. Nexus must enable Moodle mobile browser SSO and the `moodle_mobile_app` web service. |
| Nexus rejects the credential or required APIs | Retry login. If it persists, ask the Nexus administrator about mobile web-service access for your account. |
| The client still uses an old account after login | Remove `NEXUS_TOKEN` from the client's environment/configuration; it overrides the saved login. Check `NEXUS_CREDENTIAL_FILE`, then reconnect. |
| The first client connection times out | Complete `nexus-mcp login` in a terminal first, then reconnect the client. |
| Desktop sign-in is unavailable in shared mode | Remove `NEXUS_SHARED_MODE=1` from your local launcher/client environment. Shared mode is for the separate hosted server. |

## ChatGPT and hosted access

The npm launcher works with local desktop clients that can start stdio MCP servers. It does not enroll your account in the hosted ChatGPT connector.

The shared HTTP endpoint at `https://union-nexus-mcp.vercel.app/mcp` implements an authenticated Descope boundary, but per-user Nexus credential enrollment and vault retrieval remain unfinished. It is not a usable multi-user Nexus connector yet. Do not use the hosted URL as a replacement for the local command above.

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

## Safety and limits

All 11 tools are read-only and operate as the token's current user. There is no generic Moodle API tool and no submission, upload, enrollment, grading, forum tracking, or quiz-attempt operation. File reads allow only HTTPS URLs on `nexus.union.edu` under Moodle's file paths, refuse redirects, and cap downloads at 10 MB. Text and PDFs are supported; PDF extraction is capped at 50 pages, 500,000 characters, and 8 MB per decompressed stream. Discussion lists return bounded summaries; full discussion text is capped and reports truncation explicitly.

Moodle controls visibility and displayed grade totals. Missing or hidden grades stay missing; the connector does not calculate replacements. `calendar_events` excludes group-only events, so use assignment, quiz, and course-content tools before concluding there are no deadlines. Linked services and external coursework require their own integrations.

## Developer setup

### Run directly with Python

From a checkout of `feature/browser-sign-in`, on macOS/Linux:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-login.txt
python nexus_login.py
python server.py
```

On Windows, create the environment with `python -m venv .venv` and activate it with `.venv\Scripts\Activate.ps1` in PowerShell. Install Chrome or Edge, or run `python -m playwright install chromium` before login. Configure your client to start the virtual environment's absolute Python executable with the absolute path to `server.py` as its argument.

`requirements-login.txt` includes the server requirements plus Playwright. `requirements.txt` alone supports the legacy token-based server, but does not install browser-login dependencies. Setup/login messages go to stderr to keep the stdio MCP channel usable.

### Legacy manual credentials (optional)

Browser login is the recommended setup. For existing scripts or installations that already have a Moodle web-service token, the server still accepts `NEXUS_TOKEN` or a `NEXUS_CREDENTIAL_FILE` containing:

```json
{"site":"https://nexus.union.edu","token":"your-existing-token"}
```

A nonempty `NEXUS_TOKEN` takes precedence over any saved file. Otherwise the server reads the selected file or the default browser-login credential file. Restrict manually created credential files to your user (`chmod 600 /path/to/credentials.json` on POSIX). Never commit credentials or share a single-account server endpoint with another student.

### Login implementation and checks

The desktop launcher uses Moodle's existing mobile-app SSO handoff, rather than a new Okta OAuth app. It requests the Moodle confirmation page and reads the `launchapp` link before automatic native-app navigation replaces the page. Branded callbacks such as `openlms://` are accepted only as inert credential envelopes bound to Nexus and the one-time passport; browser and executable schemes are rejected.

Nexus may reuse an existing mobile-app token or create one. The login browser context is temporary: the launcher does not retain Okta cookies, passwords, or Moodle's optional private token. The resulting Nexus credential is saved locally and is not uploaded to the hosted MCP.

Run the Python checks after installing `requirements-login.txt`:

```sh
python -m unittest -v test_server.py test_login.py test_shared_server.py
```

To run the intercepted browser fixtures with an installed Chromium executable (the path below is a Linux example):

```sh
NEXUS_TEST_BROWSER=/usr/bin/chromium python -m unittest -v test_browser_login.py
```

These fixtures supply synthetic Nexus/Okta responses; they do not verify a live Union login. The separate [Chrome extension proof](extension/README.md) is for developer diagnostics and is not required for the npm launcher.

## Shared-mode credential seam

`NEXUS_SHARED_MODE=1` makes the server require a request-scoped Nexus credential. In this mode it refuses `NEXUS_TOKEN` and `NEXUS_CREDENTIAL_FILE`, and a request without its own credential fails closed. Personal stdio mode is unchanged when shared mode is unset or `0`.

This is an internal prerequisite for authenticated hosting, not a complete hosted setup. The shared HTTP entry point validates OAuth access tokens, but no credential vault is wired yet; future request middleware must retrieve only that student's vaulted Nexus token and bind it with `_request_credentials` for the duration of one request.

`shared_server:app` is the stateless HTTP entry point deployed at `https://union-nexus-mcp.vercel.app/mcp`. It validates Descope tokens against the configured issuer and JWKS, requires that exact audience and the `nexus:read` scope, and refuses to start outside shared mode or with owner credentials configured. It does not yet retrieve a student's Nexus credential, so authenticated tool calls that need Nexus remain intentionally unavailable until the server-only credential contract is configured and reviewed.
