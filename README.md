# Union Nexus MCP

Connect a local desktop MCP client to your Union Nexus account. Ask about your courses, assignments, deadlines, grades, discussions, quizzes, and course attachments. All 11 tools are read-only.

**Start here:** run the two commands for your client below and sign in through Union's normal Nexus/Okta page with your Union email/account and MFA. Enter your password only in the Union browser login window.

This is a local desktop preview, available as `nexus-assignments-mcp` on npm. Live Union login through this launcher is still awaiting verification; see [release status](RELEASE.md).

## Quick start

You need Node.js 18+ (with npm/npx), Python 3.10+ with venv/pip, and a desktop session with Chrome or Edge. Install your chosen client first.

Run the two commands for **your client** in a terminal. The first downloads the launcher and opens Union's browser login; complete sign-in and MFA before running the second. No global npm install is needed.

### Codex

```sh
npx --yes nexus-assignments-mcp@latest login
codex mcp add nexus -- npx --yes nexus-assignments-mcp@latest
```

### Claude Code

```sh
npx --yes nexus-assignments-mcp@latest login
claude mcp add --scope user nexus -- npx --yes nexus-assignments-mcp@latest
```

Restart or reconnect your client, then ask: **List my Nexus courses.**

If no browser opens, run `npx --yes nexus-assignments-mcp@latest install-browser`, then retry the login command.

To sign in again with this setup, rerun the first command. For a global install or another desktop client, follow the steps below.

## 1. Install

You need:

- Node.js 18 or newer with npm.
- Python 3.10 or newer with `venv` and pip support, available as `python3` or `python`.
- A desktop session and Chrome or Edge, or the Chromium install below.
- Your own Union account with Nexus access and an internet connection.

Run in a terminal:

```sh
npm install -g nexus-assignments-mcp@latest
nexus-mcp --help
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

Restart or reconnect your client after adding the server.

### Claude Code

If Claude Code is installed, register Nexus for your user account:

```sh
claude mcp add --scope user nexus -- nexus-mcp
```

Restart or reconnect Claude Code after adding the server.

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

Your login is saved at `~/.config/nexus-mcp/credentials.json` under your user home directory, including on Windows. Keep this file private: do not share it, paste it into chat, or commit it to Git.

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
| The client shows a different account | Run `nexus-mcp login` with the intended Union account, then restart or reconnect your client. |
| The first client connection times out | Complete `nexus-mcp login` in a terminal first, then reconnect the client. |

## Can I use this in ChatGPT?

This installation is for local desktop clients that can start MCP servers, such as Codex and Claude Code. Hosted ChatGPT account enrollment is not available yet. Use the local setup above.

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

All 11 tools are read-only and operate as your signed-in Union account. There is no generic Moodle API tool and no submission, upload, enrollment, grading, forum tracking, or quiz-attempt operation. File reads allow only HTTPS URLs on `nexus.union.edu` under Moodle's file paths, refuse redirects, and cap downloads at 10 MB. Text and PDFs are supported; PDF extraction is capped at 50 pages, 500,000 characters, and 8 MB per decompressed stream. Discussion lists return bounded summaries; full discussion text is capped and reports truncation explicitly.

Moodle controls visibility and displayed grade totals. Missing or hidden grades stay missing; the connector does not calculate replacements. `calendar_events` excludes group-only events, so use assignment, quiz, and course-content tools before concluding there are no deadlines. Linked services and external coursework require their own integrations.
