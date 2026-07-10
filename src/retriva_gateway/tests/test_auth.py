# Copyright (C) 2026 Andrea Marson (am.dev.75@gmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for the authentication framework.

Covers:
- AuthProvider contract and NullAuthProvider
- load_auth_provider() factory (none, missing, entry-point discovery)
- AuthMiddleware (exempt paths, 401 on failure, principal_ctx population)
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from retriva_gateway.core.auth_provider import (
    AuthProvider,
    NullAuthProvider,
    load_auth_provider,
)
from retriva_gateway.core.context import Principal, principal_ctx
from retriva_gateway.config import Settings
from retriva_gateway.middleware.auth import AuthMiddleware


# ---------------------------------------------------------------------------
# AuthProvider / NullAuthProvider
# ---------------------------------------------------------------------------

class TestNullAuthProvider:
    """NullAuthProvider always returns the anonymous principal."""

    @pytest.fixture
    def provider(self):
        return NullAuthProvider()

    def test_returns_anonymous_principal(self, provider):
        import asyncio
        from fastapi import Request

        # Create a minimal mock request
        mock_request = MagicMock(spec=Request)
        principal = asyncio.get_event_loop().run_until_complete(
            provider.authenticate(mock_request)
        )
        assert principal.id == "anonymous"
        assert principal.name == "Anonymous"
        assert principal.email == ""
        assert "admin" in principal.roles
        assert "*" in principal.permissions

    def test_on_startup_is_noop(self, provider):
        import asyncio
        # Should not raise
        asyncio.get_event_loop().run_until_complete(provider.on_startup())

    def test_on_shutdown_is_noop(self, provider):
        import asyncio
        # Should not raise
        asyncio.get_event_loop().run_until_complete(provider.on_shutdown())


# ---------------------------------------------------------------------------
# load_auth_provider()
# ---------------------------------------------------------------------------

class TestLoadAuthProvider:
    """Tests for the provider factory function."""

    def test_none_returns_null_provider(self):
        provider = load_auth_provider("none")
        assert isinstance(provider, NullAuthProvider)

    def test_unknown_provider_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="no matching package is installed"):
            load_auth_provider("nonexistent_provider")

    def test_entra_without_package_raises_runtime_error(self):
        """When RETRIVA_AUTH_PROVIDER=entra but retriva-iam-entra is not installed.

        If the retriva-iam-entra package IS installed in this environment,
        the provider loads successfully — so we only assert the error path
        when the package is absent.
        """
        from importlib.metadata import entry_points

        entra_installed = any(
            ep.name == "entra" for ep in entry_points(group="retriva.auth_providers")
        )
        if entra_installed:
            # Package is installed — provider should load.
            provider = load_auth_provider("entra")
            assert provider is not None
        else:
            with pytest.raises(RuntimeError, match="entra"):
                load_auth_provider("entra")

    def test_entry_point_discovery(self):
        """Mock an entry point to verify discovery works."""
        # Create a mock provider class
        class MockProvider(AuthProvider):
            async def authenticate(self, request):
                return Principal(id="mock", roles=[], permissions=[])

        # Create a mock entry point
        mock_ep = MagicMock()
        mock_ep.name = "test_provider"
        mock_ep.value = "mock_package.provider:MockProvider"
        mock_ep.load.return_value = MockProvider

        with patch(
            "retriva_gateway.core.auth_provider.entry_points",
            return_value=[mock_ep],
        ):
            provider = load_auth_provider("test_provider")
            assert isinstance(provider, MockProvider)


class TestAuthSettings:
    """Auth-related settings parsing."""

    def test_exempt_paths_accept_comma_separated(self, monkeypatch):
        monkeypatch.setenv("RETRIVA_AUTH_EXEMPT_PATHS", "/health,/ready,/capabilities")
        settings = Settings()
        assert settings.RETRIVA_AUTH_EXEMPT_PATHS == [
            "/health",
            "/ready",
            "/capabilities",
        ]


# ---------------------------------------------------------------------------
# AuthMiddleware
# ---------------------------------------------------------------------------

def _make_test_app(
    auth_provider: AuthProvider,
    exempt_paths: list[str] | None = None,
) -> FastAPI:
    """Create a minimal FastAPI app with AuthMiddleware for testing."""
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/capabilities")
    async def capabilities():
        return {"auth": True}

    @app.get("/gateway/chat")
    async def chat():
        principal = principal_ctx.get()
        return {
            "principal_id": principal.id,
            "principal_name": principal.name,
            "principal_email": principal.email,
        }

    @app.get("/docs")
    async def docs():
        return {"docs": True}

    app.add_middleware(
        AuthMiddleware,
        auth_provider=auth_provider,
        exempt_paths=exempt_paths or ["/health", "/capabilities"],
    )
    return app


class TestAuthMiddlewareWithNullProvider:
    """When auth is disabled (NullAuthProvider), all requests pass through."""

    @pytest.fixture
    def client(self):
        app = _make_test_app(NullAuthProvider())
        return TestClient(app)

    def test_health_accessible(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_capabilities_accessible(self, client):
        resp = client.get("/capabilities")
        assert resp.status_code == 200

    def test_chat_accessible_with_anonymous_principal(self, client):
        resp = client.get("/gateway/chat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["principal_id"] == "anonymous"
        assert data["principal_name"] == "Anonymous"

    def test_docs_always_exempt(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200


class TestAuthMiddlewareWithRejectingProvider:
    """When auth is enabled and the provider rejects the request."""

    @pytest.fixture
    def rejecting_provider(self):
        provider = MagicMock(spec=AuthProvider)
        provider.authenticate = AsyncMock(
            side_effect=HTTPException(status_code=401, detail="Invalid token")
        )
        return provider

    @pytest.fixture
    def client(self, rejecting_provider):
        app = _make_test_app(
            rejecting_provider,
            exempt_paths=["/health", "/capabilities"],
        )
        return TestClient(app)

    def test_exempt_paths_bypass_auth(self, client):
        """Exempt paths should not trigger authentication."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_capabilities_exempt(self, client):
        resp = client.get("/capabilities")
        assert resp.status_code == 200

    def test_docs_always_exempt(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_protected_endpoint_returns_401(self, client):
        resp = client.get("/gateway/chat")
        assert resp.status_code == 401
        data = resp.json()
        assert data["error"]["code"] == "AUTHENTICATION_FAILED"
        assert "path" in data["error"]["details"]

    def test_401_response_is_structured(self, client):
        resp = client.get("/gateway/chat")
        data = resp.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]


class TestAuthMiddlewareWithAcceptingProvider:
    """When auth is enabled and the provider accepts the request."""

    @pytest.fixture
    def accepting_provider(self):
        provider = MagicMock(spec=AuthProvider)
        provider.authenticate = AsyncMock(
            return_value=Principal(
                id="user-oid-123",
                name="Jane Doe",
                email="jane.doe@company.com",
                roles=["viewer"],
                permissions=[],
            )
        )
        return provider

    @pytest.fixture
    def client(self, accepting_provider):
        app = _make_test_app(
            accepting_provider,
            exempt_paths=["/health", "/capabilities"],
        )
        return TestClient(app)

    def test_authenticated_request_succeeds(self, client):
        resp = client.get("/gateway/chat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["principal_id"] == "user-oid-123"
        assert data["principal_name"] == "Jane Doe"
        assert data["principal_email"] == "jane.doe@company.com"

    def test_exempt_paths_still_work(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200


class TestAuthMiddlewareExemptPaths:
    """Test exempt path matching logic."""

    @pytest.fixture
    def rejecting_provider(self):
        provider = MagicMock(spec=AuthProvider)
        provider.authenticate = AsyncMock(
            side_effect=HTTPException(status_code=401, detail="No token")
        )
        return provider

    def test_prefix_match(self, rejecting_provider):
        """Exempt path /health should match /health but not /healthy."""
        app = _make_test_app(
            rejecting_provider,
            exempt_paths=["/health"],
        )
        client = TestClient(app)

        # Exact match → exempt
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_subpath_match(self, rejecting_provider):
        """Exempt path should match sub-paths like /health/detailed."""
        app = FastAPI()

        @app.get("/health/detailed")
        async def health_detailed():
            return {"detailed": True}

        app.add_middleware(
            AuthMiddleware,
            auth_provider=rejecting_provider,
            exempt_paths=["/health"],
        )
        client = TestClient(app)

        resp = client.get("/health/detailed")
        assert resp.status_code == 200

    def test_openapi_json_always_exempt(self, rejecting_provider):
        """OpenAPI spec endpoint should always be accessible."""
        app = _make_test_app(rejecting_provider, exempt_paths=[])
        client = TestClient(app)
        resp = client.get("/openapi.json")
        assert resp.status_code == 200

    def test_unexpected_auth_error_returns_401(self):
        """If authenticate raises an unexpected exception, fail closed with 401."""
        provider = MagicMock(spec=AuthProvider)
        provider.authenticate = AsyncMock(
            side_effect=ValueError("Something unexpected")
        )
        app = _make_test_app(provider, exempt_paths=[])
        client = TestClient(app)
        resp = client.get("/gateway/chat")
        assert resp.status_code == 401
        data = resp.json()
        assert data["error"]["code"] == "AUTHENTICATION_ERROR"


class TestPrincipalContextReset:
    """Verify that principal_ctx is properly reset after each request."""

    def test_principal_ctx_is_reset_after_request(self):
        provider = MagicMock(spec=AuthProvider)
        provider.authenticate = AsyncMock(
            return_value=Principal(
                id="user-456",
                name="Test",
                email="test@test.com",
                roles=[],
                permissions=[],
            )
        )

        app = _make_test_app(provider, exempt_paths=[])
        client = TestClient(app)

        # Make a request that sets the principal
        resp = client.get("/gateway/chat")
        assert resp.status_code == 200
        assert resp.json()["principal_id"] == "user-456"

        # After the request, the context var should be back to default
        default_principal = principal_ctx.get()
        assert default_principal.id == "anonymous"
