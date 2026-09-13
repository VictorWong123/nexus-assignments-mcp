# Union Nexus MCP

Read-only MCP server for asking Codex or ChatGPT about Union Nexus courses, assignments, submission status, course content, and text/PDF attachments.

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

All five tools are read-only. There is no generic Moodle API tool and no submission, upload, enrollment, or grading operation. File reads allow only HTTPS URLs on `nexus.union.edu` under Moodle's file paths, refuse redirects, and cap downloads at 10 MB. Text and PDFs are supported; PDF extraction is capped at 50 pages, 500,000 characters, and 8 MB per decompressed stream. `list_assignments` covers native Moodle assignments; use `course_contents` too because linked services and resources can contain coursework.

Run the focused checks after installing dependencies:

```sh
python -m unittest -v test_server.py
```
