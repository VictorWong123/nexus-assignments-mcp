# Release record

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
