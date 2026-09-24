import asyncio
import importlib
import os
import sys
import unittest
from unittest.mock import patch

import httpx
from fastmcp.server.auth.providers.jwt import RSAKeyPair


SHARED_ENV = {"NEXUS_SHARED_MODE": "1"}


def _import_shared_server():
    sys.modules.pop("shared_server", None)
    with patch.dict(os.environ, SHARED_ENV, clear=True):
        return importlib.import_module("shared_server")


class SharedServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = _import_shared_server()
        cls.keys = RSAKeyPair.generate()

    def token(self, *, issuer=None, audience=None, scopes=None):
        return self.keys.create_token(
            issuer=issuer or self.shared.DESCOPE_ISSUER,
            audience=audience or self.shared.RESOURCE_AUDIENCE,
            scopes=scopes if scopes is not None else [self.shared.REQUIRED_SCOPE],
        )

    async def request(self, token=None):
        with patch.dict(os.environ, SHARED_ENV, clear=True):
            verifier = self.shared._build_token_verifier(self.keys.public_key)
            app = self.shared.build_shared_app(verifier)
        headers = {"Accept": "application/json, text/event-stream"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=self.shared.PUBLIC_BASE_URL,
            ) as client:
                return await client.post(
                    self.shared.MCP_PATH,
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "1"},
                        },
                    },
                )

    def test_shared_http_requires_bearer_token(self):
        response = asyncio.run(self.request())
        self.assertEqual(response.status_code, 401)

    def test_shared_http_rejects_missing_scope(self):
        response = asyncio.run(self.request(self.token(scopes=["offline_access"])))
        self.assertEqual(response.status_code, 401)

    def test_shared_http_rejects_wrong_audience(self):
        response = asyncio.run(self.request(self.token(audience="https://example.com/mcp")))
        self.assertEqual(response.status_code, 401)

    def test_shared_http_rejects_wrong_issuer(self):
        response = asyncio.run(self.request(self.token(issuer="https://example.com")))
        self.assertEqual(response.status_code, 401)

    def test_shared_http_accepts_exact_auth_contract_and_keeps_schemas(self):
        response = asyncio.run(self.request(self.token()))
        self.assertEqual(response.status_code, 200)
        tools = asyncio.run(self.shared.mcp.list_tools())
        self.assertEqual(
            [tool.name for tool in tools],
            [
                "list_courses",
                "list_assignments",
                "assignment_status",
                "course_contents",
                "read_file",
                "grade_overview",
                "course_grades",
                "calendar_events",
                "list_discussions",
                "read_discussion",
                "list_quizzes",
            ],
        )

    def test_shared_http_refuses_owner_credentials_at_startup(self):
        with patch.dict(
            os.environ,
            {"NEXUS_SHARED_MODE": "1", "NEXUS_TOKEN": "owner"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "refuses owner"):
                self.shared.build_shared_app()
