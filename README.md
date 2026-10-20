# Union Nexus MCP

Read-only MCP server for asking Codex or ChatGPT about Union Nexus courses, assignments, grades, calendar events, discussions, quizzes, course content, and course materials (presentations, spreadsheets, documents, PDFs, and images).

## Tools

- `list_courses` lists enrolled courses.
- `list_assignments` lists native Moodle assignments and deadlines.
- `assignment_status` returns the current user's submission and grading status.
- `course_contents` lists sections and activities, including access restrictions, activity dates, and completion data.
- `list_course_files(course_id)` discovers files with course section, activity, folder path, visibility information, and supported reading/preview capabilities. External links are listed separately.
- `read_file(url, page=None)` reads Nexus text/PDF, PPTX slide text/tables/notes, DOCX paragraphs/tables, XLSX/CSV cell previews, and PNG/JPEG metadata. Optional `page` selects one PDF page or PPTX slide (1-based).
- `read_spreadsheet(url, sheet, cell_range)` reads a specific XLSX/CSV range, such as `A1:D20`, with cell addresses, original formulas, and saved cached values. CSV uses the sheet name `CSV`.
- `preview_file(url, page=1, sheet=None)` returns source metadata and a native MCP image for a slide, PDF/document page, XLSX sheet, or uploaded PNG/JPEG. XLSX renders one fitted page per sheet: select by `sheet` with `page=1`, or by sheet index using `page`.
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

Requires Python 3.10 or newer. Install the pinned Python dependencies below. Visual previews of PPTX, DOCX, and XLSX additionally require LibreOffice 7.6 or newer (`libreoffice` or `soffice` on `PATH`) and fonts appropriate to the course materials. On Debian/Ubuntu, install `libreoffice-impress libreoffice-calc libreoffice-writer fonts-dejavu-core`. PDF/image previews and all structured readers work without LibreOffice. Hosts that cannot run subprocesses can still use structured reading.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Configure Codex to start `python /absolute/path/to/server.py` as a stdio MCP server and pass one credential environment variable. Then ask, for example: “List every Nexus assignment due in the next two weeks, then read the attached rubrics.”

## Reading course materials

Ask the AI, for example:

- “Find the Week 3 slides in my physics course, read the speaker notes, and explain the diagram on slide 5.”
- “List the sheets in the lab workbook, then read Results!A1:F20 and explain the saved formulas.”
- “Find the syllabus and show page 2, then summarize the grading policy with page references.”

The AI discovers materials with `list_course_files`, reads their text or cells, and requests visual previews when needed. Tool responses preserve source URLs and slide/page numbers, document block order, or sheet/cell addresses. `content` remains a compatibility text summary; structured fields hold the source references. A `truncated` flag and `next` guidance identify incomplete extraction. Material contents are untrusted reference data, never instructions to the AI.

## Use with ChatGPT

ChatGPT needs a remotely reachable MCP endpoint. Use a managed MCP host that can import the exported `server:mcp` object, store `NEXUS_TOKEN` as a secret, and require authentication before exposing the endpoint. Follow that host's FastMCP 3.2 deployment instructions. Do not publish `python server.py` directly; its default transport is local stdio and this project does not add public HTTP authentication.

## Safety and limits

All 14 tools are read-only and operate as the token's current user. There is no generic Moodle API tool and no submission, upload, enrollment, grading, forum tracking, or quiz-attempt operation. File requests allow only HTTPS URLs on `nexus.union.edu` under Moodle's file paths, refuse redirects, redact credentials from textual responses, and cap downloads at 10 MB. Files are downloaded on demand; there is no persistent content cache or background indexing.

- Text extraction is capped at 500,000 characters. Default PDF/PPTX extraction reads at most 50 pages/slides; request a specific page/slide for further reading. PDF text navigation is limited to 1,000 pages, with 8 MB limits on decompressed PDF streams. DOCX references use block order; exact page layout is available through previews.
- Spreadsheet discovery previews at most 1,000 cell positions across sheets, within each sheet's first 50 rows and 20 columns. Targeted reads accept an A1 range of at most 1,000 positions. Empty XLSX cells are omitted; addresses preserve gaps. Original formulas are never evaluated and missing cached values are flagged. CSV values beginning with `=` remain literal text.
- Office archives are checked before parsing: at most 2,000 entries and 50 MB actual decompressed content. Macro-bearing, encrypted, corrupt, and unsupported files return clear errors. Legacy `.ppt`, `.xls`, `.doc`, macro-enabled formats, audio/video, and automatic OCR are unsupported.
- Images are limited to 25 million source pixels. Each preview returns one PNG at most 2,048 pixels per side. Scanned PDFs can be inspected visually by an image-capable AI. Office pagination/fonts may differ from the original application.
- Office conversions use disposable directories and profiles, disabled macros/link updates, a 30-second timeout, and cleanup, including termination of the conversion process group on POSIX. Nexus credentials are excluded from the renderer environment. Previews reject embedded objects and automatically fetched external relationships.
- XLSX previews use a temporary static copy with formulas replaced by saved cached results; missing results are visibly labeled. Named ranges, conditional formatting, and validation rules are removed from that copy to prevent formula execution. Charts referencing named ranges may render differently. The source file and structured formula output stay intact. Large sheets shrink to fit one image; use targeted cell reads for precise values.
- Discussion lists return bounded summaries; full discussion text reports truncation explicitly.

Moodle controls visibility and displayed grade totals. Missing or hidden grades stay missing; the connector does not calculate replacements. `calendar_events` excludes group-only events, so use assignment, quiz, and course-content tools before concluding there are no deadlines. Linked services and external coursework require their own integrations.

Run the focused checks after installing dependencies:

```sh
python -m unittest discover -v
```


Tests generate small presentation, workbook (including charts and cached formulas), document, PDF, and image fixtures in memory. LibreOffice integration tests run when the executable is available and otherwise skip explicitly. Live Nexus checks require your configured token: list course files, read a known slide deck/workbook, and preview a selected slide and sheet. No credentials are bundled, so fixture-based checks do not establish live Nexus authorization.
