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

"""ACP cohort passthrough (Spec 019 Phase 2): routing precedence and
body passthrough with a mocked CRM transport.

Verifies that the new cohort routes reach the CRM cohort API while the
legacy /acp/{kb_id} and /icp/ routes keep their exact forwarding
behavior.  No live services are contacted.
"""

from typing import List, Tuple
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from retriva_gateway.main import app

client = TestClient(app)


@pytest.fixture()
def transport_log(monkeypatch) -> List[Tuple[str, str, bytes]]:
    calls: List[Tuple[str, str, bytes]] = []

    async def fake_request(method, base_url, path, *, params=None,
                           content=None, json=None, headers=None,
                           **kwargs):
        calls.append((method, path, content or b""))
        request = httpx.Request(method, "http://core" + path)
        return httpx.Response(200, request=request, json={"ok": True},
                              headers={"content-type": "application/json"})

    monkeypatch.setattr(
        "retriva_gateway.api.v2.crm.core_client._request",
        AsyncMock(side_effect=fake_request))
    return calls


def test_cohort_list_forwards_to_cohort_api(transport_log):
    response = client.get("/api/v2/crm/acp/cohorts")
    assert response.status_code == 200
    assert ("GET", "/api/v2/crm/acp/cohorts", b"") in transport_log


def test_acp_versions_list_not_shadowed_by_legacy_kb_route(transport_log):
    """Spec 021 follow-up defect: GET /acp/versions is a single-segment
    path, so the legacy GET /acp/{kb_id} route captured it and answered
    with the bound ACP's legacy payload — the ACP console showed only
    the ACTIVE legacy ACP and none of the generated drafts.  The
    explicit guard must forward it (with its filters) to the
    PostgreSQL ACP version list."""
    response = client.get("/api/v2/crm/acp/versions")
    assert response.status_code == 200
    assert ("GET", "/api/v2/crm/acp/versions", b"") in transport_log

    response = client.get(
        "/api/v2/crm/acp/versions",
        params={"acp_id": "acp_x", "status": "DRAFT"})
    assert response.status_code == 200
    forwarded = [path for method, path, _ in transport_log]
    assert forwarded.count("/api/v2/crm/acp/versions") == 2


def test_cohort_catch_all_forwards_multisegment_paths(transport_log):
    response = client.post(
        "/api/v2/crm/acp/cohorts/cohort_1/members/org_1/decision",
        json={"actor_id": "reviewer", "decision": "INCLUDED"})
    assert response.status_code == 200
    methods_paths = [(method, path) for method, path, _ in transport_log]
    assert ("POST",
            "/api/v2/crm/acp/cohorts/cohort_1/members/org_1/decision") \
        in methods_paths


def test_cohort_approve_forwards_body(transport_log):
    response = client.post(
        "/api/v2/crm/acp/cohorts/cohort_1/approve",
        json={"actor_id": "approver", "comment": "ok"})
    assert response.status_code == 200
    assert ("POST", "/api/v2/crm/acp/cohorts/cohort_1/approve",
            b'{"actor_id":"approver","comment":"ok"}') in transport_log


def test_legacy_acp_route_forwards_to_icp_unchanged(transport_log):
    """The legacy /acp/{kb_id} gateway route keeps forwarding to the
    Core /icp/{kb_id} path (ADR-017 compatibility; untouched)."""
    response = client.get("/api/v2/crm/acp/default")
    assert response.status_code == 200
    assert ("GET", "/api/v2/crm/icp/default", b"") in transport_log


def test_legacy_icp_alias_unchanged(transport_log):
    response = client.get("/api/v2/crm/icp/default")
    assert response.status_code == 200
    assert ("GET", "/api/v2/crm/icp/default", b"") in transport_log


def test_legacy_text_route_unchanged(transport_log):
    response = client.get("/api/v2/crm/acp/default/text")
    assert response.status_code == 200
    assert ("GET", "/api/v2/crm/icp/default/text", b"") in transport_log


def test_legacy_update_route_unchanged(transport_log):
    response = client.post("/api/v2/crm/acp/default/update")
    assert response.status_code == 200
    assert ("POST", "/api/v2/crm/icp/default/update",
            b"") in transport_log


def test_console_route_forwards_via_catch_all(transport_log):
    response = client.get("/api/v2/crm/acp/cohorts/console")
    assert response.status_code == 200
    assert ("GET", "/api/v2/crm/acp/cohorts/console", b"") \
        in transport_log

def test_trusted_principal_header_injected():
    """The gateway injects the authenticated principal id as
    X-Retriva-User into every core request; client-supplied values of
    that header are never forwarded (headers are built from scratch)."""
    from retriva_gateway.core import client as core_client_mod
    from retriva_gateway.core.context import Principal, principal_ctx

    principal = Principal(id="user-42", name="User 42", email="",
                          roles=["user"], permissions=[])
    token = principal_ctx.set(principal)
    try:
        headers = core_client_mod.core_client._get_headers()
    finally:
        principal_ctx.reset(token)
    assert headers["X-Retriva-User"] == "user-42"


def test_anonymous_principal_header_when_auth_disabled():
    """With auth disabled the anonymous principal id propagates — the
    CRM records the actor honestly instead of trusting body claims."""
    from retriva_gateway.core import client as core_client_mod
    headers = core_client_mod.core_client._get_headers()
    assert headers["X-Retriva-User"] == "anonymous"


def test_service_principal_when_configured_and_auth_disabled(
        monkeypatch):
    """Spec 021 review fix (actor fidelity): with auth disabled AND a
    service principal configured, the gateway presents the machine
    principal (X-Service-Principal) instead of the meaningless
    anonymous user header — the CRM then honors declared body actor
    ids (chat:sess_..., reviewer ids) for attribution.  With auth
    ENABLED the user header stays authoritative and the service
    principal is never sent."""
    from retriva_gateway.core import client as core_client_mod
    from retriva_gateway.config import Settings
    monkeypatch.setattr(core_client_mod.settings, "RETRIVA_AUTH_PROVIDER",
                        "none")
    monkeypatch.setattr(core_client_mod.settings,
                        "RETRIVA_SERVICE_PRINCIPAL", " svc-research ")
    headers = core_client_mod.core_client._get_headers()
    assert headers["X-Service-Principal"] == "svc-research"
    assert "X-Retriva-User" not in headers

    # Auth enabled: the user header wins, the principal is never sent.
    monkeypatch.setattr(core_client_mod.settings, "RETRIVA_AUTH_PROVIDER",
                        "entra")
    from retriva_gateway.core.context import Principal, principal_ctx
    principal = Principal(id="user-42", name="U", email="",
                          roles=["user"], permissions=[])
    token = principal_ctx.set(principal)
    try:
        headers = core_client_mod.core_client._get_headers()
    finally:
        principal_ctx.reset(token)
    assert headers["X-Retriva-User"] == "user-42"
    assert "X-Service-Principal" not in headers
