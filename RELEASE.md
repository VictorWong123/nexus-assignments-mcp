# Release status

Union Nexus MCP is a local desktop preview with browser login through Union Nexus/Okta, including MFA. Install it using the [README](README.md).

- Published on November 23, 2026: [`nexus-assignments-mcp@0.1.0`](https://www.npmjs.com/package/nexus-assignments-mcp). The executable is `nexus-mcp`.
- Each user signs in with their own Union account. The resulting credential is saved on their computer.
- The connector exposes 11 read-only tools for courses, assignments, deadlines, grades, discussions, quizzes, and attachments.
- Hosted ChatGPT account enrollment is not available yet.

## What has been checked

On November 23, 2026, the published package was downloaded from npm using `npx`. Its checksum matched the tested release, the launcher help command passed, and the server initialized and exposed all 11 tools using a synthetic credential. Automatic dependency setup also passed from the release tarball. All 58 automated checks passed, including simulated browser-login responses. No student data was requested by these checks.

A live Union login through the desktop launcher and a second student's account remain unverified. These checks do not guarantee that every Union account has the required Nexus permissions.
