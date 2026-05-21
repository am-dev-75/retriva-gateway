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

import pytest
from fastapi.testclient import TestClient
from retriva_gateway.main import app

client = TestClient(app)

def test_health():
    response = client.get("/gateway/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "version": "0.1.0"}

def test_capabilities():
    response = client.get("/gateway/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert "chat" in data
    assert "knowledge_bases" in data
    assert "ingestion" in data

# ---------------------------------------------------------------------------
# /gateway/kbs — pass-through to Core (Phase 4 of the KB SDD)
#
# These tests stub the ``core_client`` boundary so they remain unit-level
# (no running Core). End-to-end coverage against a real Core is tracked in
# tests/test_gateway_kbs_e2e.py (skipped by default; requires services).
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock, patch


def test_kbs_list_translates_core_response_to_webui_shape():
    fake_core_payload = {
        "kbs": [
            {
                "kb_id": "default",
                "name": "default",
                "description": "Default knowledge base",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "settings": {},
                "document_count": 5,
            },
            {
                "kb_id": "eng",
                "name": "Engineering",
                "description": None,
                "created_at": "2026-01-02T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z",
                "settings": {},
                "document_count": 0,
            },
        ]
    }
    with patch(
        "retriva_gateway.api.v2.kbs.core_client.list_kbs",
        AsyncMock(return_value=fake_core_payload),
    ):
        response = client.get("/gateway/kbs")

    assert response.status_code == 200
    items = response.json()
    # Translation: kb_id -> id, status synthesized, count preserved.
    assert items == [
        {
            "id": "default",
            "name": "default",
            "description": "Default knowledge base",
            "document_count": 5,
            "status": "active",
        },
        {
            "id": "eng",
            "name": "Engineering",
            "description": None,
            "document_count": 0,
            "status": "active",
        },
    ]


def test_kbs_create_forwards_to_core_and_translates_response():
    captured: dict = {}

    async def fake_create(payload):
        captured["payload"] = payload
        return {
            "kb_id": "engineering",
            "name": "Engineering",
            "description": "Eng docs",
            "created_at": "2026-01-02T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "settings": {},
            "document_count": 0,
        }

    with patch(
        "retriva_gateway.api.v2.kbs.core_client.create_kb",
        AsyncMock(side_effect=fake_create),
    ):
        response = client.post(
            "/gateway/kbs",
            json={"name": "Engineering", "description": "Eng docs"},
        )

    assert response.status_code == 200, response.text
    # ``exclude_none=True`` means kb_id (omitted by client) is not forwarded;
    # description (provided) is forwarded.
    assert captured["payload"] == {"name": "Engineering", "description": "Eng docs"}

    body = response.json()
    assert body["id"] == "engineering"
    assert body["name"] == "Engineering"
    assert body["status"] == "active"


def test_kbs_create_with_explicit_kb_id_forwards_field():
    captured: dict = {}

    async def fake_create(payload):
        captured["payload"] = payload
        return {
            "kb_id": payload["kb_id"],
            "name": payload["name"],
            "description": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "settings": {},
            "document_count": 0,
        }

    with patch(
        "retriva_gateway.api.v2.kbs.core_client.create_kb",
        AsyncMock(side_effect=fake_create),
    ):
        response = client.post(
            "/gateway/kbs", json={"kb_id": "custom_id", "name": "Custom"}
        )

    assert response.status_code == 200
    assert captured["payload"] == {"kb_id": "custom_id", "name": "Custom"}


def test_kbs_get_translates_single_response():
    with patch(
        "retriva_gateway.api.v2.kbs.core_client.get_kb",
        AsyncMock(
            return_value={
                "kb_id": "default",
                "name": "default",
                "description": None,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "settings": {},
                "document_count": 7,
            }
        ),
    ):
        response = client.get("/gateway/kbs/default")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "default"
    assert body["document_count"] == 7
    assert body["status"] == "active"


def test_kbs_patch_forwards_only_present_fields():
    captured: dict = {}

    async def fake_update(kb_id, payload):
        captured["kb_id"] = kb_id
        captured["payload"] = payload
        return {
            "kb_id": kb_id,
            "name": payload.get("name", "old"),
            "description": payload.get("description", "old"),
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "settings": {},
            "document_count": 0,
        }

    with patch(
        "retriva_gateway.api.v2.kbs.core_client.update_kb",
        AsyncMock(side_effect=fake_update),
    ):
        # Only ``name`` provided — description must NOT be forwarded as null
        # (would clobber Core-side value).
        response = client.patch(
            "/gateway/kbs/eng", json={"name": "Engineering v2"}
        )

    assert response.status_code == 200
    assert captured["kb_id"] == "eng"
    assert captured["payload"] == {"name": "Engineering v2"}


def test_kbs_delete_returns_synthetic_status_body():
    delete_mock = AsyncMock(return_value=None)
    with patch(
        "retriva_gateway.api.v2.kbs.core_client.delete_kb", delete_mock
    ):
        response = client.delete("/gateway/kbs/some-kb")

    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}
    delete_mock.assert_awaited_once_with("some-kb")


def test_kbs_propagates_core_404():
    """A 404 from Core must reach the WebUI as 404, not 500."""
    import httpx

    request = httpx.Request("GET", "http://core/api/v2/kbs/missing")
    response_404 = httpx.Response(
        404, request=request, json={"detail": "KB not found: missing"}
    )
    err = httpx.HTTPStatusError(
        "Not Found", request=request, response=response_404
    )

    with patch(
        "retriva_gateway.api.v2.kbs.core_client.get_kb",
        AsyncMock(side_effect=err),
    ):
        response = client.get("/gateway/kbs/missing")

    assert response.status_code == 404
    # The Gateway's global exception handler wraps the upstream message.
    body = response.json()
    assert "missing" in body["error"]["message"]


def test_kbs_propagates_core_409_on_duplicate_create():
    """Slug collision from Core (409) must reach the WebUI as 409."""
    import httpx

    request = httpx.Request("POST", "http://core/api/v2/kbs")
    response_409 = httpx.Response(
        409, request=request, json={"detail": "KB already exists: eng"}
    )
    err = httpx.HTTPStatusError(
        "Conflict", request=request, response=response_409
    )

    with patch(
        "retriva_gateway.api.v2.kbs.core_client.create_kb",
        AsyncMock(side_effect=err),
    ):
        response = client.post("/gateway/kbs", json={"name": "Eng"})

    assert response.status_code == 409


def test_kbs_propagates_core_409_on_default_delete():
    """Refusal to delete the 'default' KB (409 from Core) is preserved."""
    import httpx

    request = httpx.Request("DELETE", "http://core/api/v2/kbs/default")
    response_409 = httpx.Response(
        409,
        request=request,
        json={"detail": "The 'default' KB cannot be deleted."},
    )
    err = httpx.HTTPStatusError(
        "Conflict", request=request, response=response_409
    )

    with patch(
        "retriva_gateway.api.v2.kbs.core_client.delete_kb",
        AsyncMock(side_effect=err),
    ):
        response = client.delete("/gateway/kbs/default")

    assert response.status_code == 409


def test_kbs_propagates_core_422_on_invalid_kb_id():
    """Validation failure from Core (422) is preserved."""
    import httpx

    request = httpx.Request("POST", "http://core/api/v2/kbs")
    response_422 = httpx.Response(
        422,
        request=request,
        json={"detail": "kb_id='UPPER' must match ^[a-z0-9]..."},
    )
    err = httpx.HTTPStatusError(
        "Unprocessable", request=request, response=response_422
    )

    with patch(
        "retriva_gateway.api.v2.kbs.core_client.create_kb",
        AsyncMock(side_effect=err),
    ):
        response = client.post(
            "/gateway/kbs", json={"kb_id": "UPPER", "name": "x"}
        )

    assert response.status_code == 422


def test_kbs_no_in_memory_storage_remains():
    """Belt-and-braces: the legacy in-memory ``_kbs`` dict must be gone."""
    from retriva_gateway.api.v2 import kbs as kbs_module
    assert not hasattr(kbs_module, "_kbs"), (
        "Phase 4 must remove the in-memory mock store from the Gateway."
    )

def test_speech_placeholder():
    response = client.post("/gateway/speech/transcriptions")
    assert response.status_code == 501
