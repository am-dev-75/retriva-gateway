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

"""Spec 038 Phase 5 — Gateway campaign proxy trust, bounds, precedence
and typed-error preservation (mocked CRM transport; no live services)."""

from typing import Any, Dict, List
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from retriva_gateway.main import app

client = TestClient(app)


def _response(status: int, payload: Dict[str, Any],
              content_type: str = "application/json") -> httpx.Response:
    request = httpx.Request("GET", "http://core")
    import json as _json
    return httpx.Response(
        status, request=request, content=_json.dumps(payload).encode(),
        headers={"content-type": content_type})


@pytest.fixture()
def transport(monkeypatch) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []

    async def fake_request(method, base_url, path, *, params=None,
                           content=None, json=None, headers=None,
                           **kwargs):
        calls.append({"method": method, "base_url": base_url,
                      "path": path, "params": params,
                      "content": content, "headers": headers,
                      "timeout": kwargs.get("timeout")})
        return _response(200, {"ok": True})

    monkeypatch.setattr(
        "retriva_gateway.api.v2.crm.core_client._request",
        AsyncMock(side_effect=fake_request))
    return calls


def test_put_grace_policy_is_forwarded(transport):
    response = client.put(
        "/api/v2/crm/campaigns/grace-policy",
        json={"grace_days": 90, "timezone": "UTC"})
    assert response.status_code == 200
    call = transport[-1]
    assert call["method"] == "PUT"
    assert call["path"] == "/api/v2/crm/campaigns/grace-policy"
    assert call["content"] == b'{"grace_days":90,"timezone":"UTC"}'


def test_static_paths_reach_the_fixed_crm_prefix(transport):
    for path in ("permissions", "console", "exclusions",
                 "grace-policy/history", "import-batches/b1/rows",
                 "eligibility/evaluate"):
        method = "POST" if path.endswith("evaluate") else "GET"
        response = client.request(method,
                                  f"/api/v2/crm/campaigns/{path}")
        assert response.status_code == 200
        assert transport[-1]["path"] == \
            f"/api/v2/crm/campaigns/{path}"


def test_query_parameters_are_preserved(transport):
    response = client.get(
        "/api/v2/crm/campaigns/exclusions",
        params={"limit": 25, "cursor": "abc|def",
                "status": "ACTIVE"})
    assert response.status_code == 200
    assert transport[-1]["params"] == [
        ("limit", "25"), ("cursor", "abc|def"), ("status", "ACTIVE")]


def test_typed_crm_error_is_preserved_verbatim(monkeypatch):
    async def raising(method, base_url, path, **kwargs):
        request = httpx.Request(method, "http://core" + path)
        return _response(409, {"code": "CAMPAIGN_VERSION_CONFLICT",
                               "message": "stale expectation"})
    # Simulate the client's raise_for_status path.
    async def fake(method, base_url, path, **kwargs):
        resp = await raising(method, base_url, path, **kwargs)
        resp.raise_for_status()
        return resp
    monkeypatch.setattr(
        "retriva_gateway.api.v2.crm.core_client._request",
        AsyncMock(side_effect=fake))
    response = client.post(
        "/api/v2/crm/campaigns/exclusions/excl_1/review",
        json={"expected_status": "APPROVED"})
    assert response.status_code == 409
    assert response.json() == {"code": "CAMPAIGN_VERSION_CONFLICT",
                               "message": "stale expectation"}


def test_client_identity_headers_are_not_forwarded(transport):
    response = client.get(
        "/api/v2/crm/campaigns/exclusions",
        headers={"X-Retriva-User": "impostor",
                 "X-Service-Principal": "impostor",
                 "X-Tenant": "cust_0007"})
    assert response.status_code == 200
    assert transport[-1]["headers"] is None


def test_only_content_type_is_merged_for_bodies(transport):
    client.post("/api/v2/crm/campaigns/exclusions",
                json={"organization_id": "org_1",
                      "reason_code": "MANUAL_EXCLUSION"},
                headers={"X-Retriva-User": "impostor",
                         "X-Custom": "x"})
    headers = transport[-1]["headers"]
    assert headers == {"Content-Type": "application/json"}


def test_core_client_rebuilds_trusted_identity(monkeypatch):
    from retriva_gateway.core import client as client_mod
    from retriva_gateway.core.context import Principal, principal_ctx
    from retriva_gateway.config import settings

    token = principal_ctx.set(Principal(
        id="user-42", roles=[], permissions=[]))
    try:
        monkeypatch.setattr(settings, "RETRIVA_AUTH_PROVIDER", "oidc")
        headers = client_mod.core_client._get_headers()
        assert headers["X-Retriva-User"] == "user-42"
        assert "X-Service-Principal" not in headers
        monkeypatch.setattr(settings, "RETRIVA_AUTH_PROVIDER", "none")
        monkeypatch.setattr(settings, "RETRIVA_SERVICE_PRINCIPAL",
                            "svc-gateway")
        headers = client_mod.core_client._get_headers()
        assert "X-Retriva-User" not in headers
        assert headers.get("X-Service-Principal") == "svc-gateway"
        # Documented limitation: without a configured service principal
        # the anonymous principal id is presented (never a client value).
        monkeypatch.setattr(settings, "RETRIVA_SERVICE_PRINCIPAL", "")
        headers = client_mod.core_client._get_headers()
        assert headers.get("X-Retriva-User") == "user-42"
    finally:
        principal_ctx.reset(token)


def test_oversized_body_is_refused(transport, monkeypatch):
    from retriva_gateway.api.v2 import crm as crm_mod
    monkeypatch.setattr(crm_mod, "CAMPAIGN_PROXY_MAX_BODY", 16)
    response = client.post(
        "/api/v2/crm/campaigns/exclusions",
        json={"organization_id": "org_1",
              "reason_code": "MANUAL_EXCLUSION"})
    assert response.status_code == 413
    assert response.json()["code"] == "REQUEST_TOO_LARGE"
    assert transport == []


def test_oversized_response_is_refused(monkeypatch):
    async def big(method, base_url, path, **kwargs):
        return _response(200, {"payload": "x" * 20000})
    monkeypatch.setattr(
        "retriva_gateway.api.v2.crm.core_client._request",
        AsyncMock(side_effect=big))
    from retriva_gateway.api.v2 import crm as crm_mod
    monkeypatch.setattr(crm_mod, "CAMPAIGN_PROXY_MAX_RESPONSE", 1024)
    response = client.get("/api/v2/crm/campaigns/exclusions")
    assert response.status_code == 502
    assert response.json()["code"] == \
        "UPSTREAM_RESPONSE_TOO_LARGE"


def test_upstream_timeout_becomes_bounded_504(monkeypatch):
    async def boom(method, base_url, path, **kwargs):
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(
        "retriva_gateway.api.v2.crm.core_client._request",
        AsyncMock(side_effect=boom))
    response = client.get("/api/v2/crm/campaigns/exclusions")
    assert response.status_code == 504
    assert response.json()["code"] == "UPSTREAM_TIMEOUT"


def test_unsafe_path_is_refused(transport):
    response = client.get(
        "/api/v2/crm/campaigns/%5C..%5Csecret")
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_PROXY_PATH"
    assert transport == []


def test_proxy_sets_a_timeout_bound(transport):
    client.get("/api/v2/crm/campaigns/exclusions")
    assert transport[-1]["timeout"] == 30.0


def test_campaign_governance_health_is_bounded():
    response = client.get("/api/v2/crm/campaign-governance/health")
    assert response.status_code == 200
    body = response.json()
    assert body["campaign_proxy_registered"] is True
    assert body["campaign_tool_count"] == 33
    assert body["campaign_tools_ok"] is True
    assert body["permission_vocabulary_expected"] == "final_v1"
    assert body["interim_mapping_expected_absent"] is True
    assert body["console_surfaces"] == "crm_served_via_campaign_proxy"
    text = response.text
    for forbidden in ("cust_0007", "tenant", "http://", "localhost",
                      "password", "secret"):
        assert forbidden not in text, forbidden


def test_collection_root_forwards_without_slash_redirect(transport):
    response = client.post(
        "/api/v2/crm/campaigns",
        json={"campaign_code": "C-1", "name": "C"})
    assert response.status_code == 200
    assert transport[-1]["method"] == "POST"
    assert transport[-1]["path"] == "/api/v2/crm/campaigns"


def test_collection_root_trailing_slash_uses_canonical_upstream(transport):
    response = client.get("/api/v2/crm/campaigns/")
    assert response.status_code == 200
    assert transport[-1]["path"] == "/api/v2/crm/campaigns"


def test_collection_root_never_emits_a_redirect(transport):
    response = client.post(
        "/api/v2/crm/campaigns",
        json={"campaign_code": "C-1", "name": "C"},
        follow_redirects=False)
    assert response.status_code == 200
    assert response.history == []
    assert "location" not in {k.lower() for k in response.headers}
    assert len(transport) == 1


def test_collection_root_following_client_has_zero_redirects(transport):
    response = client.get("/api/v2/crm/campaigns",
                          follow_redirects=True)
    assert response.status_code == 200
    assert response.history == []
    assert len(transport) == 1


def test_collection_root_preserves_query_string(transport):
    response = client.get(
        "/api/v2/crm/campaigns",
        params=[("limit", "2"), ("status", "ACTIVE"),
                ("cursor", "a|b"), ("status", "DRAFT")])
    assert response.status_code == 200
    assert sorted(transport[-1]["params"]) == sorted([
        ("limit", "2"), ("status", "ACTIVE"), ("cursor", "a|b"),
        ("status", "DRAFT")])


def test_child_trailing_slash_uses_the_canonical_upstream_path(transport):
    response = client.get("/api/v2/crm/campaigns/exclusions/")
    assert response.status_code == 200
    assert transport[-1]["path"] == "/api/v2/crm/campaigns/exclusions"


def test_proxy_uses_the_fixed_core_origin(transport):
    client.get("/api/v2/crm/campaigns")
    from retriva_gateway.core.client import core_client
    assert transport[-1]["base_url"] == core_client.ingestion_base_url


@pytest.mark.parametrize("path", [
    "/api/v2/crm/campaigns/%2e%2e/%2e%2e/secret",
    "/api/v2/crm/campaigns/..%2fsecret",
    "/api/v2/crm/campaigns/%2e%2e%5csecret",
    "/api/v2/crm/campaigns/%252e%252e%255csecret",
])
def test_encoded_traversal_is_refused(path, transport):
    response = client.get(path)
    assert response.status_code in (400, 404), (path, response.status_code)
    if response.status_code == 400:
        assert response.json()["code"] == "INVALID_PROXY_PATH"
    assert transport == []


def test_dynamic_campaign_reference_still_routes_to_child_path(transport):
    response = client.get("/api/v2/crm/campaigns/2026-Q1/lineage")
    assert response.status_code == 200
    assert transport[-1]["path"] ==         "/api/v2/crm/campaigns/2026-Q1/lineage"


def test_double_encoded_traversal_is_rejected_in_real_asgi(transport):
    import asyncio

    async def run():
        transport_client = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
                transport=transport_client,
                base_url="http://testserver") as async_client:
            return await async_client.get(
                "/api/v2/crm/campaigns/%252e%252e%252fsecret")

    response = asyncio.run(run())
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_PROXY_PATH"
    assert transport == []


@pytest.mark.parametrize("encoded", ["%3F", "%23"])
def test_encoded_query_or_fragment_is_rejected(encoded, transport):
    response = client.get(
        f"/api/v2/crm/campaigns/exclusions{encoded}injected=1")
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_PROXY_PATH"
    assert transport == []
