"""ERP import chat tools: analyze_company_import / commit_company_import.

Direct executor tests with a mocked CRM transport (pattern of
test_chat_qualification_policy.py): trusted-attachment enforcement,
request shape, chat-summary presentation, and the registry contract
(additive tools, no "direct" in names, commit flagged destructive).
No live services are contacted.
"""
import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from retriva_gateway.agent.tools import (
    ToolContext,
    _tool_analyze_company_import,
    _tool_commit_company_import,
    build_default_tool_registry,
)


def _ctx(session_id="sess_import", attachments=("att_wb",)):
    return ToolContext(
        session_id=session_id,
        kb_id="default",
        allowed_attachment_ids=list(attachments),
        correlation_id="corr_1",
    )


def _response(path, data, status_code=200):
    req = httpx.Request("POST", "http://core" + path)
    return httpx.Response(status_code, request=req, json=data)


ANALYSIS = {
    "status": "NEEDS_REVIEW",
    "import_batch_id": "ibth_test_1",
    "counters": {
        "rows_received": 3,
        "new_organizations_proposed": 2,
        "exact_matches": 1,
        "probable_or_ambiguous": 1,
        "conflicts": 0,
    },
    "review_url": "/api/v2/crm/imports/batches/ibth_test_1/review",
}


def test_registry_registers_import_tools_additively():
    registry = build_default_tool_registry()
    names = registry.names()
    assert "analyze_company_import" in names
    assert "commit_company_import" in names
    # Policy: no tool name mentions "direct".
    assert all("direct" not in name for name in names)
    # Pre-existing tools untouched.
    for name in ("qualify_candidates", "get_qualification_readiness",
                 "cancel_qualification_job"):
        assert name in names
    commit = registry.get("commit_company_import")
    assert commit.destructive is True
    analyze = registry.get("analyze_company_import")
    assert analyze.destructive is False
    # The schema declares the trusted attachment parameter.
    schema = analyze.parameters
    assert schema["required"] == ["attachment_id"]
    assert "profile" in schema["properties"]


def test_analyze_requires_session_attachment():
    async def run():
        ctx = _ctx(attachments=())  # no attachments in context
        return await _tool_analyze_company_import(
            {"attachment_id": "att_wb"}, ctx)
    with pytest.raises(Exception) as excinfo:
        asyncio.run(run())
    assert "Attach" in str(excinfo.value)


def test_analyze_rejects_invented_attachment_ids():
    async def run():
        ctx = _ctx()
        return await _tool_analyze_company_import(
            {"attachment_id": "att_not_in_session"}, ctx)
    with pytest.raises(Exception) as excinfo:
        asyncio.run(run())
    assert "not an attachment" in str(excinfo.value)


def test_analyze_proxies_to_crm_and_builds_chat_summary():
    captured = {}

    async def transport(method, base_url, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kwargs.get("json")
        return _response(path, ANALYSIS)

    async def run():
        with patch("retriva_gateway.agent.tools.core_client._request",
                   AsyncMock(side_effect=transport)):
            return await _tool_analyze_company_import(
                {"attachment_id": "att_wb", "source_system": "erp",
                 "profile": "AUTO"}, _ctx())

    result = asyncio.run(run())
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v2/crm/imports/analyze"
    payload = captured["json"]
    assert payload["session_id"] == "sess_import"
    assert payload["attachment_id"] == "att_wb"
    assert payload["profile"] == "AUTO"
    # Chat presentation: summary + review link + the explicit
    # "canonical data unchanged" explanation.
    assert result["chat_summary"]
    assert "NOT changed" in result["chat_summary"] or \
        "not changed" in result["chat_summary"]
    assert result["review_url"] in result["chat_summary"]
    assert "ibth_test_1" in result["chat_summary"]
    assert "2 new organizations" in result["chat_summary"]


def test_analyze_surfaces_ambiguous_profile_selection():
    ambiguous = {
        "status": "PROFILE_SELECTION_REQUIRED",
        "import_batch_id": None,
        "profile_selection": {
            "selected_profile": None,
            "ambiguous": True,
            "reason": "profiles A and B are within the ambiguity margin",
            "alternatives": [
                {"profile": "ERP_CUSTOMER_EXPORT_V1"},
                {"profile": "ERP_SUPPLIER_EXPORT_V1"},
            ],
        },
    }
    captured = {}

    async def transport(method, base_url, path, **kwargs):
        captured["path"] = path
        return _response(path, ambiguous)

    async def run():
        with patch("retriva_gateway.agent.tools.core_client._request",
                   AsyncMock(side_effect=transport)):
            return await _tool_analyze_company_import(
                {"attachment_id": "att_wb"}, _ctx())

    result = asyncio.run(run())
    assert result["status"] == "PROFILE_SELECTION_REQUIRED"
    # The tool tells the model to ask the user instead of guessing.
    assert "ERP_CUSTOMER_EXPORT_V1" in result["chat_summary"]
    assert "ERP_SUPPLIER_EXPORT_V1" in result["chat_summary"]


def test_analyze_propagates_upstream_errors():
    async def transport(method, base_url, path, **kwargs):
        req = httpx.Request("POST", "http://core" + path)
        error = httpx.Response(503, request=req,
                               json={"detail": "PostgreSQL store is disabled"})
        error.raise_for_status()

    async def run():
        with patch("retriva_gateway.agent.tools.core_client._request",
                   AsyncMock(side_effect=transport)):
            return await _tool_analyze_company_import(
                {"attachment_id": "att_wb"}, _ctx())

    with pytest.raises(Exception) as excinfo:
        asyncio.run(run())
    assert "503" in str(excinfo.value)


def test_commit_requires_batch_id():
    async def run():
        return await _tool_commit_company_import({}, _ctx())
    with pytest.raises(Exception):
        asyncio.run(run())


def test_commit_proxies_with_session_actor_and_key():
    captured = {}

    async def transport(method, base_url, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kwargs.get("json")
        return _response(path, {
            "status": "COMMITTED",
            "import_batch_id": "ibth_test_1",
            "applied": {"organizations_created": 2},
            "reconciliation_summary": {"counters": {
                "created_organizations": 2,
                "updated_organizations": 1,
                "roles_added": 2,
                "identifiers_added": 3,
            }},
            "reconciliation_url":
                "/api/v2/crm/imports/batches/ibth_test_1/reconciliation",
        })

    async def run():
        with patch("retriva_gateway.agent.tools.core_client._request",
                   AsyncMock(side_effect=transport)):
            return await _tool_commit_company_import(
                {"import_batch_id": "ibth_test_1",
                 "idempotency_key": "key-1"}, _ctx())

    result = asyncio.run(run())
    assert captured["method"] == "POST"
    assert captured["path"] == \
        "/api/v2/crm/imports/batches/ibth_test_1/commit"
    assert captured["json"]["actor_id"] == "chat:sess_import"
    assert captured["json"]["idempotency_key"] == "key-1"
    # Chat presentation: discloses created and updated records and the
    # reconciliation report location.
    assert "committed" in result["chat_summary"]
    assert "2 organizations created" in result["chat_summary"]
    assert result["reconciliation_url"] in result["chat_summary"]


def test_commit_marks_idempotent_replay_in_summary():
    async def transport(method, base_url, path, **kwargs):
        return _response(path, {
            "status": "COMMITTED",
            "import_batch_id": "ibth_test_1",
            "idempotent_replay": True,
            "applied": {},
            "reconciliation_summary": {"counters": {}},
            "reconciliation_url": "/api/v2/crm/imports/batches/"
                                  "ibth_test_1/reconciliation",
        })

    async def run():
        with patch("retriva_gateway.agent.tools.core_client._request",
                   AsyncMock(side_effect=transport)):
            return await _tool_commit_company_import(
                {"import_batch_id": "ibth_test_1"}, _ctx())

    result = asyncio.run(run())
    assert "idempotent replay" in result["chat_summary"]


def test_tool_descriptions_carry_the_approval_contract():
    registry = build_default_tool_registry()
    analyze = registry.get("analyze_company_import")
    commit = registry.get("commit_company_import")
    # Analysis never writes canonical data.
    assert "NEVER changes canonical" in analyze.description
    # Commit is never automatic.
    assert "EXPLICITLY" in commit.description
    assert "never automatically" in commit.description
    assert "APPROVED" in commit.description
