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

"""Internal routing-status endpoint (Spec 001 Phase E; architecture
§10).

Gateway-local, authenticated with the EXISTING Gateway internal-service
token convention (``X-Service-Token`` compared against
``GATEWAY_INTERNAL_SERVICE_TOKEN`` — the accepted pattern of
``api/internal/sources.py``), distinct from the dedicated Gateway-to-
Core classifier service token.  Not in the public OpenAPI contract;
no CORS; internal deployment exposure only — authentication and
internal placement are the trust controls, never obscurity.

The response is bounded and content-free: metric counters and gauges,
a numeric latency summary, the Phase C registry content-free
statistics snapshot, the classifier policy status, the shadow ring
counts and expiry, and safe failure counts.  It never contains
messages, prompts, classifier responses, individual shadow records,
resource identifiers, tenant/principal/session/KB identifiers,
confirmation records, tokens, claim IDs, idempotency keys, API keys,
service tokens, endpoint URLs, raw error text, or stack traces.
"""

from __future__ import annotations

import hmac
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import JSONResponse

from retriva_gateway.config import settings
from retriva_gateway.core.routing.context import (
    get_workflow_context_registry,
)
from retriva_gateway.core.routing.metrics import routing_metrics
from retriva_gateway.core.routing.policy import (
    shadow_diagnostics_ring,
)

router = APIRouter(prefix="/internal/routing", tags=["internal"])


async def _verify_service_token(
        x_service_token: Optional[str] = Header(None)) -> None:
    """Verify the Gateway internal-service token (constant-time), the
    accepted internal-endpoint convention."""
    expected = settings.GATEWAY_INTERNAL_SERVICE_TOKEN
    if not expected or not hmac.compare_digest(x_service_token or "",
                                               expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing service token.")


@router.get("/status")
async def routing_status(
        x_service_token: Optional[str] = Header(None)):
    """Content-free routing status (Spec 001 Phase E)."""
    await _verify_service_token(x_service_token)
    metrics = routing_metrics().snapshot()
    registry = get_workflow_context_registry().snapshot()
    ring = shadow_diagnostics_ring().summary()
    # Content-free registry snapshot: counts and the last purge time
    # only — never any record content.
    registry_summary = {
        "entries_total": registry.entries_total,
        "pending_total": registry.pending_total,
        "claimed_total": registry.claimed_total,
        "expired_purged_total": registry.expired_purged_total,
        "capacity_rejections_total":
            registry.capacity_rejections_total,
        "last_purge_epoch": (
            registry.last_purge_at.timestamp()
            if registry.last_purge_at is not None else None),
    }
    # Classifier policy status: enabled flag, mode, and the safe
    # configuration FACT only (the canonical provider is Core-owned
    # deployment-global configuration the Gateway never selects or
    # observes; no secrets, no endpoints, no model names).
    classifier_status = {
        "policy_enabled":
            bool(settings.AGENT_INTENT_CLASSIFIER_ENABLED),
        "mode": settings.AGENT_INTENT_ROUTER_MODE,
        "min_confidence":
            float(settings.AGENT_INTENT_CLASSIFIER_MIN_CONFIDENCE),
        "safe_workflow_min_confidence": float(
            settings.AGENT_INTENT_CLASSIFIER_SAFE_WORKFLOW_MIN_CONFIDENCE),
        "fail_mode": settings.AGENT_INTENT_CLASSIFIER_FAIL_MODE,
        "transport": "core-deployment-global",
    }
    return JSONResponse(content={
        "status": "ok",
        "mode": settings.AGENT_INTENT_ROUTER_MODE,
        "metrics": metrics,
        "workflow_context_registry": registry_summary,
        "shadow_diagnostics": ring,
        "classifier": classifier_status,
    })
