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

"""Authentication middleware.

Intercepts every inbound request and delegates authentication to the
active :class:`~retriva_gateway.core.auth_provider.AuthProvider`.

When the provider is :class:`NullAuthProvider` (``RETRIVA_AUTH_PROVIDER=none``),
the middleware is effectively a no-op — the anonymous principal is set on the
request context and the request proceeds.

When a real provider is active, the middleware enforces authentication on all
non-exempt paths.  Exempt paths (e.g. ``/health``, ``/capabilities``) are
configured via ``RETRIVA_AUTH_EXEMPT_PATHS``.
"""

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger

from retriva_gateway.core.auth_provider import AuthProvider
from retriva_gateway.core.context import principal_ctx
from retriva_gateway.core.models import ErrorResponse, ErrorDetail


class AuthMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that enforces authentication via a pluggable provider.

    Parameters
    ----------
    app:
        The ASGI application.
    auth_provider:
        The active :class:`AuthProvider` instance.
    exempt_paths:
        URL path prefixes that bypass authentication (e.g. health checks).
    """

    def __init__(self, app, auth_provider: AuthProvider, exempt_paths: list[str] | None = None):
        super().__init__(app)
        self._auth_provider = auth_provider
        self._exempt_paths = [p.rstrip("/") for p in (exempt_paths or [])]

    def _is_exempt(self, path: str) -> bool:
        """Check whether *path* matches any configured exempt prefix.

        The match is prefix-based so that ``/health`` exempts ``/health``,
        ``/healthz``, etc.  The OpenAPI docs endpoints (``/docs``,
        ``/openapi.json``, ``/redoc``) are always exempt.
        """
        # Always allow OpenAPI introspection endpoints.
        always_exempt = ("/docs", "/openapi.json", "/redoc")
        if path in always_exempt:
            return True

        normalized = path.rstrip("/")
        for exempt in self._exempt_paths:
            if normalized == exempt or normalized.startswith(exempt + "/"):
                return True
        return False

    async def dispatch(self, request: Request, call_next):
        # Check whether the path requires authentication.
        path = request.url.path
        if self._is_exempt(path):
            return await call_next(request)

        try:
            principal = await self._auth_provider.authenticate(request)
        except HTTPException as exc:
            # Authentication failed — return structured 401.
            logger.warning(
                "Authentication failed on {} {} — status={}",
                request.method,
                path,
                exc.status_code,
            )
            return JSONResponse(
                status_code=exc.status_code,
                content=ErrorResponse(
                    error=ErrorDetail(
                        code="AUTHENTICATION_FAILED",
                        message=exc.detail if isinstance(exc.detail, str) else "Authentication required.",
                        details={"path": path},
                    )
                ).model_dump(),
            )
        except Exception:
            # Unexpected error during authentication — fail closed.
            logger.exception("Unexpected error during authentication on {} {}", request.method, path)
            return JSONResponse(
                status_code=401,
                content=ErrorResponse(
                    error=ErrorDetail(
                        code="AUTHENTICATION_ERROR",
                        message="An unexpected error occurred during authentication.",
                        details={"path": path},
                    )
                ).model_dump(),
            )

        # Set the authenticated principal on the request context.
        token = principal_ctx.set(principal)
        try:
            response = await call_next(request)
        finally:
            principal_ctx.reset(token)

        return response
