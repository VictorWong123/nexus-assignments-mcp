"""Authenticated stateless HTTP entry point for the shared Nexus MCP."""

from __future__ import annotations

import os

from fastmcp.server.auth.providers.descope import DescopeProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier

from server import _shared_mode, mcp

PUBLIC_BASE_URL = "https://union-nexus-mcp.vercel.app"
MCP_PATH = "/mcp"
RESOURCE_AUDIENCE = f"{PUBLIC_BASE_URL}{MCP_PATH}"
REQUIRED_SCOPE = "nexus:read"
DESCOPE_CONFIG_URL = (
    "https://api.descope.com/v1/apps/agentic/"
    "P3Jl0aRvt7UXBxEaLnG2xqKvOJcm/"
    "RS3Jl17cYiS1eRcpqkDAvevdebaKG/.well-known/openid-configuration"
)
DESCOPE_ISSUER = DESCOPE_CONFIG_URL.removesuffix(
    "/.well-known/openid-configuration"
)
DESCOPE_JWKS_URL = (
    "https://api.descope.com/P3Jl0aRvt7UXBxEaLnG2xqKvOJcm/.well-known/jwks.json"
)


def _validate_shared_environment() -> None:
    if not _shared_mode():
        raise RuntimeError("Shared HTTP entry point requires NEXUS_SHARED_MODE=1")
    if os.environ.get("NEXUS_TOKEN", "").strip() or os.environ.get(
        "NEXUS_CREDENTIAL_FILE", ""
    ).strip():
        raise RuntimeError("Shared HTTP entry point refuses owner credentials")


def _build_token_verifier(public_key: str | bytes | None = None) -> JWTVerifier:
    key = {"public_key": public_key} if public_key else {"jwks_uri": DESCOPE_JWKS_URL}
    return JWTVerifier(
        **key,
        issuer=DESCOPE_ISSUER,
        audience=RESOURCE_AUDIENCE,
        algorithm="RS256",
        required_scopes=[REQUIRED_SCOPE],
    )


def build_shared_app(token_verifier: JWTVerifier | None = None):
    """Build the protected HTTP app; credential retrieval middleware is added later."""
    _validate_shared_environment()
    mcp.auth = DescopeProvider(
        base_url=PUBLIC_BASE_URL,
        config_url=DESCOPE_CONFIG_URL,
        required_scopes=[REQUIRED_SCOPE],
        scopes_supported=[REQUIRED_SCOPE, "offline_access"],
        resource_name="Union Nexus",
        token_verifier=token_verifier or _build_token_verifier(),
    )
    return mcp.http_app(path=MCP_PATH, stateless_http=True)


app = build_shared_app()
