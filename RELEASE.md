# Release status

Union Nexus MCP is a local desktop preview with browser login through Union Nexus/Okta, including MFA. Install it using the [README](README.md).

- The npm launcher is `nexus-assignments-mcp`, version `0.1.0`. The executable is `nexus-mcp`.
- Each user signs in with their own Union account. The resulting credential is saved on their computer.
- The connector exposes 11 read-only tools for courses, assignments, deadlines, grades, discussions, quizzes, and attachments.
- Hosted ChatGPT account enrollment is not available yet.

## What has been checked

The GitHub npm install and the installed launcher's help command were checked on November 20, 2026. Earlier checks covered package installation, discovery of all 11 tools with synthetic credentials, and simulated browser-login responses.

A live Union login through the desktop launcher and a second student's account remain unverified. These checks do not guarantee that every Union account has the required Nexus permissions.
