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

"""Active-collection resolution for multi-tenant requests.

Determines the effective Qdrant collection for a request based on the
authenticated principal's authorization and the client's optional
collection selection.

Resolution rules
-----------------
1. Auth disabled (anonymous principal with empty ``allowed_collections``):
   use the deployment default (``RETRIVA_DEFAULT_COLLECTION``).
2. Auth enabled, principal has exactly one allowed collection:
   use it automatically.
3. Auth enabled, client explicitly selects a collection:
   validate it is in ``allowed_collections``; 403 if not.
4. Auth enabled, no explicit selection, principal has ``default_collection``:
   use it if it is in ``allowed_collections``; 403 otherwise.
5. Auth enabled, multiple collections, no selection, no default:
   400 — ambiguous, client must select.
"""

from typing import Optional

from fastapi import HTTPException, status

from retriva_gateway.core.context import Principal


def resolve_active_collection(
    principal: Principal,
    requested_collection: Optional[str],
    default_fallback: str,
) -> str:
    """Resolve the effective Qdrant collection for this request.

    Parameters
    ----------
    principal:
        The authenticated (or anonymous) principal.
    requested_collection:
        The collection explicitly requested by the client (e.g. via
        ``X-Retriva-Requested-Collection`` header).  ``None`` if not provided.
    default_fallback:
        The deployment-level default collection
        (``settings.RETRIVA_DEFAULT_COLLECTION``).

    Returns
    -------
    str
        The validated collection name to forward to Core.

    Raises
    ------
    HTTPException(403)
        Principal is not authorized for the requested/default collection.
    HTTPException(400)
        Multiple collections are available but no selection was made and
        no ``default_collection`` is configured on the principal.
    """
    allowed = principal.allowed_collections

    # ── Anonymous / legacy mode (no collection enforcement) ──────────
    if not allowed:
        # If the client explicitly requested a collection, honor it
        # (no enforcement in anonymous mode).
        return requested_collection or default_fallback

    # ── Single collection — auto-select ──────────────────────────────
    if len(allowed) == 1:
        target = allowed[0]
        # If the client explicitly requested a *different* collection, reject.
        if requested_collection and requested_collection != target:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Access denied: collection '{requested_collection}' "
                    f"is not in your allowed collections."
                ),
            )
        return target

    # ── Multiple collections ─────────────────────────────────────────
    if requested_collection:
        if requested_collection in allowed:
            return requested_collection
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Access denied: collection '{requested_collection}' "
                f"is not in your allowed collections."
            ),
        )

    # No explicit selection — try the principal's default.
    if principal.default_collection:
        if principal.default_collection in allowed:
            return principal.default_collection
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Principal's default collection "
                f"'{principal.default_collection}' is not in "
                f"allowed_collections."
            ),
        )

    # No selection, no default, multiple options — ambiguous.
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "Multiple collections are available but no collection was "
            "selected. Please specify a collection via the "
            "X-Retriva-Requested-Collection header. "
            f"Available: {allowed}"
        ),
    )
