# Release record

## Current distribution and verification status

- Student setup: install the npm launcher from the `feature/browser-sign-in` GitHub branch and run `nexus-mcp login`. Follow the [installation guide](README.md#1-install).
- Package: `nexus-assignments-mcp` version `0.1.0`, executable `nexus-mcp`. It is private/unpublished; there is no npm-registry install by package name.
- Login: Union Nexus/Okta browser sign-in, including MFA, with the resulting Nexus credential stored locally. Manual token entry is optional legacy configuration.
- Hosted ChatGPT enrollment and per-user Nexus credential retrieval remain unfinished. The desktop login does not connect a student to the shared hosted server.

### Installation guide checked November 20, 2026

The documented GitHub npm install completed in a temporary global prefix, and the installed `nexus-mcp --help` command succeeded. Documentation links, JSON examples, and launcher settings were checked against source. This check did not install the launcher's Python dependencies or perform a live Union login.

### Desktop launcher checks recorded October 19, 2026

- An npm tarball installed into a clean prefix. The launcher installed its Python dependencies and completed MCP initialization and discovery of all 11 tools using a synthetic credential. No student data was requested.
- Headless Chromium exercised intercepted synthetic Nexus → Okta → Nexus fixtures, including the auto-clicking confirmation page, branded callback parsing, mismatched-passport rejection, ambiguous-link rejection, and browser cleanup.
- Python checks covered tools, saved credentials, required API permissions, and shared-server isolation. Extension checks remained intact.
- A live Union sign-in through the desktop launcher and a second ordinary student's account remain unverified. The owner-account live proof below used the separate Chrome extension, not this launcher.

### Chrome extension proof recorded September 23, 2026

The owner-account Nexus/Okta login completed, the credential matched the one-time passport, the Nexus API returned the authenticated student identity, and all 12 functions required by the 11 tools were available (453 functions total). This verifies one account's extension handoff only. Cross-account isolation has synthetic concurrency coverage; a second live student account remains a public-release verification gate. See [extension instructions](extension/README.md).

## 2026-09-23 — shared authentication boundary

- Source commit: `d54f5af`
- Production URL: `https://union-nexus-mcp.vercel.app`
- Immutable deployment URL: `https://union-nexus-14dxcwh54-victorwong123s-projects.vercel.app`
- Vercel deployment: `dpl_EPhNHQYR6t3Xnv9TZwFtBKjwJind` (`READY`, production)
- Verification: 28 Python tests passed; unauthenticated and malformed-token MCP requests returned HTTP 401; protected-resource metadata advertised the exact MCP resource, Descope issuer, and required scope; Descope discovery advertised S256; development and credential paths returned HTTP 404.

Provider configuration at deployment:

- Descope project: `P3Jl0aRvt7UXBxEaLnG2xqKvOJcm`
- MCP resource: `RS3Jl17cYiS1eRcpqkDAvevdebaKG`
- Backend confidential client: `UDNKbDBhUnZ0N1VYQnhFYUxuRzJ4cUt2T0pjbTpUUEEzSmwxWk50blVKanF0ekh5MEhqakw4R3B2OWwj`
- Credential Connection: `union-nexus`
- Policy: default block; the selected backend client may use only the `union-nexus` Connection; OAuth clients may request only this MCP resource and `nexus:read` through user authorization code access.
- Production environment names: `NEXUS_SHARED_MODE`, `NEXUS_DESCOPE_CLIENT_ID`, and secret `NEXUS_DESCOPE_CLIENT_SECRET`. No values are stored in the repository.

This release provides the authenticated, fail-closed MCP boundary only. No enrollment credential or real student Nexus token is stored. Student enrollment and request-scoped Nexus credential retrieval are not connected, so this is not yet a usable multi-user connector.
