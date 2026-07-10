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

"""Pluggable authentication provider interface.

The Gateway supports external authentication providers via a plugin mechanism.
The active provider is selected by the ``RETRIVA_AUTH_PROVIDER`` environment
variable:

* ``none``  – no authentication (default); the anonymous principal is used.
* ``entra`` – Microsoft Entra ID (requires the ``retriva-iam-entra`` package).

Third-party providers register themselves as Python entry points in the
``retriva.auth_providers`` group.  The entry point name must match the value
of ``RETRIVA_AUTH_PROVIDER``.
"""

from abc import ABC, abstractmethod
from importlib.metadata import entry_points

from fastapi import Request
from loguru import logger

from retriva_gateway.core.context import Principal


class AuthProvider(ABC):
    """Abstract base class for authentication providers.

    Each provider must be able to:
    1. Validate an incoming HTTP request and return a ``Principal``.
    2. Optionally perform startup tasks (e.g. fetching JWKS).

    Providers that need configuration should read their own environment
    variables (prefixed appropriately) rather than relying on the Gateway's
    ``Settings`` object.
    """

    @abstractmethod
    async def authenticate(self, request: Request) -> Principal:
        """Validate the request and return a populated Principal.

        Implementations must raise ``fastapi.HTTPException(status_code=401)``
        when authentication fails.  The middleware will catch this and return
        a JSON 401 response.

        .. warning::
           Implementations must **never** log raw tokens, Authorization
           headers, or other credential material.
        """
        ...

    async def on_startup(self) -> None:
        """Optional startup hook.

        Called once during Gateway lifespan startup.  Use this to fetch
        OIDC discovery metadata, pre-cache JWKS keys, or validate that
        required configuration is present (fail closed).
        """

    async def on_shutdown(self) -> None:
        """Optional shutdown hook.

        Called once during Gateway lifespan shutdown.  Use this to clean
        up resources such as HTTP client sessions.
        """


class NullAuthProvider(AuthProvider):
    """No-op provider used when authentication is disabled.

    Returns the default anonymous principal for every request.
    """

    async def authenticate(self, request: Request) -> Principal:
        return Principal(
            id="anonymous",
            name="Anonymous",
            email="",
            roles=["admin"],
            permissions=["*"],
        )


def load_auth_provider(name: str) -> AuthProvider:
    """Instantiate the authentication provider identified by *name*.

    Parameters
    ----------
    name:
        The value of ``RETRIVA_AUTH_PROVIDER``.  ``"none"`` returns a
        :class:`NullAuthProvider`.  Any other value triggers entry-point
        discovery in the ``retriva.auth_providers`` group.

    Returns
    -------
    AuthProvider
        A ready-to-use (but not yet started) provider instance.

    Raises
    ------
    RuntimeError
        If the requested provider is not installed.
    """
    if name == "none":
        logger.info("Auth provider: none (authentication disabled)")
        return NullAuthProvider()

    # Discover installed providers via entry_points.
    discovered = entry_points(group="retriva.auth_providers")

    for ep in discovered:
        if ep.name == name:
            provider_cls = ep.load()
            logger.info("Auth provider '{}' loaded from {}", name, ep.value)
            return provider_cls()

    raise RuntimeError(
        f"Auth provider '{name}' is configured (RETRIVA_AUTH_PROVIDER={name}) "
        f"but no matching package is installed.  "
        f"Install the corresponding Retriva Pro package "
        f"(e.g. 'pip install retriva-iam-{name}') and restart the Gateway."
    )
