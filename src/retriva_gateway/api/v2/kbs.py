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

"""
Gateway KB endpoints — Phase 4 of the KB SDD.

The Gateway is now a **pure pass-through** to Retriva Core's
``/api/v2/kbs`` API. There is no in-memory storage and no
business logic here; the only work this module does is:

1. Validate inbound request bodies against the WebUI-facing schema.
2. Translate Core's response shape to the WebUI-facing shape:
   - Core's ``kb_id`` -> WebUI's ``id``
   - synthesize ``status`` as a constant (SDD RD-4)
3. Let upstream ``httpx.HTTPStatusError`` propagate so the existing
   ``global_exception_handler`` middleware preserves Core's status code
   (404 / 409 / 422 / 500) without reinterpretation.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Response, status
from loguru import logger
from pydantic import BaseModel, Field

from retriva_gateway.core.client import core_client

router = APIRouter(prefix="/kbs", tags=["kbs"])


# ---------------------------------------------------------------------------
# WebUI-facing models
#
# These are intentionally kept stable across this migration to avoid
# changing the WebUI contract. The shape diverges from Core's ``KBResponse``
# in two places (see ``_to_webui`` below):
#   * ``id``     (Gateway) <- ``kb_id``  (Core)
#   * ``status`` is synthesized (Core does not yet expose lifecycle state).
# ---------------------------------------------------------------------------

class KnowledgeBase(BaseModel):
    id: str
    collection: str
    name: str
    description: Optional[str] = None
    document_count: int = 0
    status: str = "active"


class KBCreate(BaseModel):
    """Create-KB request body.

    The optional ``kb_id`` field implements SDD RD-1: callers may either
    supply an explicit id (validated server-side by Core) or omit it and
    let Core derive one from ``name``.
    """

    kb_id: Optional[str] = None
    name: str
    description: Optional[str] = None


class KBUpdate(BaseModel):
    """Patch-KB request body. Only supplied fields are applied."""

    name: Optional[str] = None
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Core -> WebUI translation
# ---------------------------------------------------------------------------

#: Synthesized lifecycle state (SDD RD-4). Core does not persist a status
#: column yet; we surface a stable string the WebUI already handles. When
#: Core gains a real state machine, replace this with ``core_kb["status"]``.
_SYNTHESIZED_STATUS = "active"


def _to_webui(core_kb: Dict[str, Any]) -> KnowledgeBase:
    """Map a Core ``KBResponse`` dict to the WebUI-facing ``KnowledgeBase``.

    Tolerant to missing optional fields so a Core schema extension (e.g.
    new ``status``) does not break the Gateway until the mapping is
    explicitly updated.
    """
    return KnowledgeBase(
        id=core_kb["kb_id"],
        collection=core_kb.get("collection_name", ""),
        name=core_kb["name"],
        description=core_kb.get("description"),
        document_count=core_kb.get("document_count", 0),
        status=core_kb.get("status", _SYNTHESIZED_STATUS),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=List[KnowledgeBase])
async def list_kbs() -> List[KnowledgeBase]:
    """List all KBs.

    Core returns ``{"kbs": [<KBResponse>, ...]}``; the WebUI expects a bare
    array. We unwrap and translate per-item.
    """
    payload = await core_client.list_kbs()
    items = payload.get("kbs", []) if isinstance(payload, dict) else payload
    return [_to_webui(kb) for kb in items]


@router.post("", response_model=KnowledgeBase)
async def create_kb(kb_in: KBCreate) -> KnowledgeBase:
    """Create a KB. Forwards to Core, which owns slugification and conflict
    detection (SDD RD-1). Core returns 201 + body on success; the Gateway
    surfaces 200 + body to remain wire-compatible with the existing WebUI
    expectation (the WebUI checks only that the response is 2xx)."""
    body = kb_in.model_dump(exclude_none=True)
    created = await core_client.create_kb(body)
    return _to_webui(created)


@router.get("/{kb_id}", response_model=KnowledgeBase)
async def get_kb(kb_id: str) -> KnowledgeBase:
    """Fetch a single KB. 404 from Core is preserved by the middleware."""
    core_kb = await core_client.get_kb(kb_id)
    return _to_webui(core_kb)


@router.patch("/{kb_id}", response_model=KnowledgeBase)
async def update_kb(kb_id: str, kb_in: KBUpdate) -> KnowledgeBase:
    """Update mutable fields. ``id`` is immutable.

    Only fields the client explicitly sent are forwarded; this lets Core
    distinguish "leave alone" (omit) from "set to empty" (send "").
    """
    body = kb_in.model_dump(exclude_none=True)
    updated = await core_client.update_kb(kb_id, body)
    return _to_webui(updated)


@router.delete("/{kb_id}")
async def delete_kb(kb_id: str) -> Dict[str, str]:
    """Delete a KB. Core runs the cascade (Phase 3).

    The WebUI's existing client expects a JSON body shaped as
    ``{"status": "deleted"}``; we synthesize it here because Core returns
    204 with no body.
    """
    await core_client.delete_kb(kb_id)
    return {"status": "deleted"}
