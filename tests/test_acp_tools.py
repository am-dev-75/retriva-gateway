"""ACP chat tools (Spec 020 / ADR-023): direct executor tests with a
mocked CRM transport (pattern of test_import_tools.py).

Covers: registry contract (15 tools, destructive flags), typed error
mapping, review-URL building, actor attribution, tenant-isolation
(none of the tools accepts a tenant), boundary behavior (propose does
not approve/generate; approval refuses unresolved decisions; generation
never activates), and header construction (the trusted principal rides
the gateway-injected header, never a client-supplied value).
No live services are contacted.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from retriva_gateway.agent import tools as acp_tools
from retriva_gateway.agent.tools import (
    ToolContext,
    _tool_activate_acp,
    _tool_approve_acp,
    _tool_approve_acp_cohort,
    _tool_generate_acp,
    _tool_get_acp_cohort,
    _tool_get_acp_generation_run,
    _tool_get_acp_lineage,
    _tool_get_acp_version,
    _tool_get_active_acp,
    _tool_list_acp_cohort_members,
    _tool_propose_acp_cohort,
    _tool_rollback_acp_activation,
    _tool_submit_acp_cohort_for_review,
    _tool_submit_acp_for_review,
    _tool_update_acp_cohort_member,
    build_default_tool_registry,
)

ACP_TOOL_NAMES = [
    "propose_acp_cohort",
    "get_acp_cohort",
    "list_acp_cohort_members",
    "update_acp_cohort_member",
    "submit_acp_cohort_for_review",
    "approve_acp_cohort",
    "generate_acp",
    "get_acp_generation_run",
    "get_acp_version",
    "submit_acp_for_review",
    "approve_acp",
    "activate_acp",
    "rollback_acp_activation",
    "get_active_acp",
    "get_acp_lineage",
]


def _ctx(session_id="sess_acp"):
    return ToolContext(session_id=session_id, kb_id="default",
                       correlation_id="corr_acp")


def _response(method, path, data, status_code=200):
    req = httpx.Request(method, "http://core" + path)
    resp = httpx.Response(status_code, request=req, json=data)
    if status_code >= 400:
        resp.raise_for_status()
    return resp


def test_registry_registers_all_acp_tools_additively():
    registry = build_default_tool_registry()
    names = registry.names()
    for name in ACP_TOOL_NAMES:
        assert name in names
    # Existing tools untouched.
    for name in ("qualify_candidates", "analyze_company_import",
                 "commit_company_import", "create_campaign"):
        assert name in names
    # Destructive flags: approval/activation/rollback only.
    destructive = {t.name for t in
                   [registry.get(n) for n in ACP_TOOL_NAMES]
                   if t.destructive}
    assert destructive == {"approve_acp_cohort", "approve_acp",
                           "activate_acp", "rollback_acp_activation"}


def test_acp_tool_schemas_reject_unknown_arguments():
    registry = build_default_tool_registry()
    for name in ACP_TOOL_NAMES:
        schema = registry.get(name).parameters
        assert schema["additionalProperties"] is False


def test_no_acp_tool_accepts_tenant_argument():
    registry = build_default_tool_registry()
    for name in ACP_TOOL_NAMES:
        props = registry.get(name).parameters.get("properties", {})
        assert "tenant_id" not in props, name


def test_propose_sends_attribution_actor_and_projects_output():
    propose_resp = {
        "acp_cohort_id": "acpc_1",
        "status": "ACTIVE",
        "current_version": 1,
        "policy_version": "pol_abc",
        "counts": {"included": 0, "excluded": 2, "pending_review": 3,
                   "outlier": 1, "insufficient_data": 1},
        "proposal_counts": {"considered": 7, "proposed_now": 3,
                            "excluded_recorded_now": 2,
                            "cap_skipped": 1},
    }
    version_resp = {
        "acp_cohort_id": "acpc_1",
        "acp_cohort_version_id": "acpcv_1",
        "version": 1,
        "status": "DRAFT",
        "members": [
            {"organization_id": "org_1", "canonical_legal_name": "A",
             "decision": "PENDING_REVIEW",
             "identity_resolution_status": "UNRESOLVED",
             "freshness_status": "FRESH"},
            {"organization_id": "org_2", "canonical_legal_name": "B",
             "decision": "EXCLUDED", "freshness_status": "STALE"},
        ],
    }
    captured = []

    async def fake_request(method, base_url, path, **kwargs):
        captured.append({"method": method, "path": path,
                         "json": kwargs.get("json")})
        if method == "POST":
            return _response(method, path, propose_resp)
        return _response(method, path, version_resp)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_propose_acp_cohort(
            {"name": "Active customers"}, _ctx()))
    assert captured[0]["method"] == "POST"
    assert captured[0]["path"] == "/api/v2/crm/acp/cohorts"
    assert captured[0]["json"]["actor_id"] == "chat:sess_acp"
    assert "tenant_id" not in captured[0]["json"]
    assert "proposal_policy" not in captured[0]["json"]
    assert result["cohort_id"] == "acpc_1"
    assert result["cohort_version_id"] == "acpcv_1"
    assert result["status"] == "ACTIVE"
    assert result["policy_id"] == "pol_abc"
    assert result["policy_version"] == "pol_abc"
    assert result["considered_count"] == 7
    assert result["pending_review_count"] == 3
    assert result["excluded_count"] == 2
    assert result["insufficient_data_count"] == 1
    assert result["outlier_candidate_count"] == 1
    assert result["identity_review_count"] == 1
    assert result["blocking_issues"][0]["code"] == \
        "IDENTITY_REVIEW_REQUIRED"
    assert result["blocking_issues"][1]["code"] == "PENDING_REVIEW"
    assert result["warnings"][0]["code"] in ("CAP_SKIPPED",
                                             "INSUFFICIENT_DATA",
                                             "STALE_EVIDENCE")
    assert result["review_url"].startswith("http")


def test_propose_zero_considered_is_typed_no_eligible_customers():
    propose_resp = {
        "acp_cohort_id": "acpc_empty", "status": "ACTIVE",
        "current_version": 1, "policy_version": "pol_abc",
        "counts": {"included": 0, "excluded": 0, "pending_review": 0,
                   "outlier": 0, "insufficient_data": 0},
        "proposal_counts": {"considered": 0, "proposed_now": 0,
                            "excluded_recorded_now": 0,
                            "cap_skipped": 0},
    }
    version_resp = {"acp_cohort_version_id": "acpcv_empty",
                    "version": 1, "status": "DRAFT", "members": []}

    async def fake_request(method, base_url, path, **kwargs):
        if method == "POST":
            return _response(method, path, propose_resp)
        return _response(method, path, version_resp)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_propose_acp_cohort(
            {"name": "Active customers"}, _ctx()))
    assert result["error"]["code"] == "no_eligible_customers"


def test_propose_maps_typed_upstream_errors():
    async def fake_request(method, base_url, path, **kwargs):
        return _response(method, path, {
            "code": "ACP_PERMISSION_DENIED",
            "detail": "actor is not authorized"}, status_code=403)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_propose_acp_cohort(
            {"name": "X"}, _ctx()))
    assert result["error"]["code"] == "permission_denied"
    assert result["error"]["upstream_code"] == "ACP_PERMISSION_DENIED"


def test_propose_maps_postgres_unavailable():
    async def fake_request(method, base_url, path, **kwargs):
        return _response(method, path, {
            "code": "ACP_POSTGRES_UNAVAILABLE",
            "detail": "store disabled"}, status_code=503)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_propose_acp_cohort(
            {"name": "X"}, _ctx()))
    assert result["error"]["code"] == "postgres_unavailable"


def test_update_member_decision_route_and_payload():
    captured = []

    async def fake_request(method, base_url, path, **kwargs):
        captured.append({"method": method, "path": path,
                         "json": kwargs.get("json")})
        return _response(method, path, {"decision": "INCLUDED",
                                        "weight": 1.0})

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_update_acp_cohort_member(
            {"cohort_id": "acpc_1", "organization_id": "org_1",
             "decision": "INCLUDED", "weight": 1.0,
             "reviewer_comment": "ok"}, _ctx()))
    assert captured[0]["path"] == (
        "/api/v2/crm/acp/cohorts/acpc_1/members/org_1/decision")
    assert captured[0]["json"]["decision"] == "INCLUDED"
    assert captured[0]["json"]["actor_id"] == "chat:sess_acp"
    assert "error" not in result


def test_update_member_rejects_unknown_decision():
    with pytest.raises(acp_tools.ToolExecutionError):
        asyncio.run(_tool_update_acp_cohort_member(
            {"cohort_id": "acpc_1", "organization_id": "org_1",
             "decision": "AUTO_INCLUDE"}, _ctx()))


def test_approve_cohort_refuses_unresolved_decisions():
    cohort_resp = {"acp_cohort_id": "acpc_1", "status": "ACTIVE",
                   "current_version": 1}
    version_resp = {
        "acp_cohort_id": "acpc_1",
        "acp_cohort_version_id": "acpcv_1", "version": 1,
        "status": "DRAFT",
        "members": [
            {"organization_id": "org_1", "decision": "PENDING_REVIEW"},
        ],
    }

    async def fake_request(method, base_url, path, **kwargs):
        if path.endswith("/versions/1"):
            return _response(method, path, version_resp)
        return _response(method, path, cohort_resp)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_approve_acp_cohort(
            {"cohort_id": "acpc_1"}, _ctx()))
    assert result["error"]["code"] == "unresolved_decisions"
    assert result["error"]["pending_review_count"] == 1


def test_approve_cohort_calls_approve_route_only():
    version_resp = {
        "acp_cohort_id": "acpc_1",
        "acp_cohort_version_id": "acpcv_1", "version": 1,
        "status": "DRAFT", "members": [
            {"organization_id": "org_1", "decision": "INCLUDED"}],
    }
    approve_resp = {
        "acp_cohort_id": "acpc_1", "acp_cohort_version_id": "acpcv_1",
        "version": 1, "status": "APPROVED",
        "snapshot_hash": "sha256:deadbeef",
        "member_count_included": 1,
    }
    calls = []

    async def fake_request(method, base_url, path, **kwargs):
        calls.append((method, path))
        if method == "POST":
            return _response(method, path, approve_resp)
        return _response(method, path, version_resp)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_approve_acp_cohort(
            {"cohort_id": "acpc_1", "version_number": 1}, _ctx()))
    assert calls == [("GET",
                      "/api/v2/crm/acp/cohorts/acpc_1/versions/1"),
                     ("POST",
                      "/api/v2/crm/acp/cohorts/acpc_1/approve")]
    assert result["status"] == "APPROVED"
    assert result["snapshot_hash"] == "sha256:deadbeef"
    # Approval never generates: no generation route was called.
    assert all("generation" not in p for _, p in calls)


def test_generate_posts_generation_route_and_projects_output():
    gen_resp = {
        "acp_generation_run_id": "acpr_1",
        "acp_cohort_version_id": "acpcv_1",
        "snapshot_hash": "sha256:snap",
        "status": "COMPLETED",
        "acp_version_id": "acpv_1",
        "acp_id": "icp_1",
        "acp_version_number": 2,
        "contributing_count": 3,
        "skipped_count": 0,
        "payload_sha256": "sha256:payload",
        "semantic_validation_status": "PASSED",
        "review_readiness": "READY",
        "acp_version_status": "DRAFT",
        "payload_summary": {"confidence": 0.8, "dimension_count": 5,
                            "typed_dimension_count": 4,
                            "warnings": []},
        "idempotent_replay": False,
    }
    captured = []

    async def fake_request(method, base_url, path, **kwargs):
        captured.append({"method": method, "path": path,
                         "json": kwargs.get("json")})
        return _response(method, path, gen_resp)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_generate_acp(
            {"acp_cohort_version_id": "acpcv_1",
             "idempotency_key": "k1"}, _ctx()))
    assert captured[0]["path"] == "/api/v2/crm/acp/generation-runs"
    assert captured[0]["json"]["acp_cohort_version_id"] == "acpcv_1"
    assert captured[0]["json"]["actor_id"] == "chat:sess_acp"
    assert result["generation_run_id"] == "acpr_1"
    assert result["acp_version_id"] == "acpv_1"
    assert result["snapshot_hash"] == "sha256:snap"
    assert result["payload_hash"] == "sha256:payload"
    assert result["contributing_count"] == 3
    assert result["skipped_count"] == 0
    assert result["confidence_and_coverage"]["confidence"] == 0.8
    assert result["status"] == "COMPLETED"
    assert result["review_url"].startswith("http")
    # Generation never activates.
    assert captured[0]["path"].endswith("generation-runs")


def test_generate_failed_run_maps_to_generation_failure():
    gen_resp = {
        "acp_generation_run_id": "acpr_2",
        "status": "FAILED",
        "failure_code": "GENERATION_ERROR",
    }

    async def fake_request(method, base_url, path, **kwargs):
        return _response(method, path, gen_resp)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_generate_acp(
            {"acp_cohort_version_id": "acpcv_1"}, _ctx()))
    assert result["error"]["code"] == "generation_failure"


def test_activate_verifies_single_active_and_reports_ledger():
    activate_resp = {"acp_id": "icp_1", "version": 2,
                     "status": "ACTIVE"}
    active_resp = {"acp_id": "icp_1", "version": 2, "status": "ACTIVE"}
    lineage_resp = {
        "acp_id": "icp_1", "version": 2,
        "activations": [
            {"activation_id": "act_1", "operation": "ACTIVATE",
             "activated_at": "2026-09-29T12:00:00+00:00",
             "rollback_of_activation_id": None},
        ],
    }
    captured = []

    async def fake_request(method, base_url, path, **kwargs):
        captured.append((method, path))
        if path.endswith("/activate"):
            return _response(method, path, activate_resp)
        if path.endswith("/active"):
            return _response(method, path, active_resp)
        return _response(method, path, lineage_resp)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_activate_acp(
            {"acp_id": "icp_1", "version_number": 2}, _ctx()))
    assert ("POST",
            "/api/v2/crm/acp/versions/icp_1/2/activate") in captured
    assert result["activation_id"] == "act_1"
    assert result["active_acp_id"] == "icp_1"
    assert result["active_acp_version"] == 2
    assert result["single_active"] is True
    assert result["rollback_reference"] == "act_1"


def test_activate_conflict_maps_to_activation_conflict():
    async def fake_request(method, base_url, path, **kwargs):
        return _response(method, path, {
            "code": "ACP_ACTIVE_CONFLICT",
            "detail": "another ACP version is already ACTIVE"},
            status_code=409)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_activate_acp(
            {"acp_id": "icp_1", "version_number": 2}, _ctx()))
    assert result["error"]["code"] == "activation_conflict"


def test_rollback_posts_rollback_route_and_reports_ledger():
    rollback_resp = {"acp_id": "icp_1", "version": 1,
                     "status": "ACTIVE"}
    active_resp = {"acp_id": "icp_1", "version": 1, "status": "ACTIVE"}
    lineage_resp = {
        "activations": [
            {"activation_id": "act_2", "operation": "ROLLBACK",
             "activated_at": "2026-09-29T13:00:00+00:00",
             "rollback_of_activation_id": "act_1"},
        ],
    }
    captured = []

    async def fake_request(method, base_url, path, **kwargs):
        captured.append((method, path))
        if path.endswith("/rollback"):
            return _response(method, path, rollback_resp)
        if path.endswith("/active"):
            return _response(method, path, active_resp)
        return _response(method, path, lineage_resp)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_rollback_acp_activation(
            {"acp_id": "icp_1", "version_number": 1,
             "rollback_of_activation_id": "act_1"}, _ctx()))
    assert ("POST",
            "/api/v2/crm/acp/versions/icp_1/1/rollback") in captured
    assert result["activation_id"] == "act_2"
    assert result["rollback_of_activation_id"] == "act_1"
    assert result["single_active"] is True
    assert result["history_preserved"] is True


def test_get_active_maps_no_active_acp():
    async def fake_request(method, base_url, path, **kwargs):
        return _response(method, path, {
            "code": "ACP_NO_ACTIVE",
            "detail": "no active ACP"}, status_code=400)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_get_active_acp({}, _ctx()))
    assert result["error"]["code"] == "no_active_acp"


def test_get_active_hides_profile_payload_content():
    active_resp = {
        "acp_id": "icp_1", "version": 1, "status": "ACTIVE",
        "origin": "LEGACY_SEED", "payload_sha256": "sha256:p",
        "profile": {"label": "Average customer", "summary": "x" * 500,
                    "dimensions": ["secret-evidence"]},
    }

    async def fake_request(method, base_url, path, **kwargs):
        return _response(method, path, active_resp)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_get_active_acp({}, _ctx()))
    assert "profile" not in result
    assert "secret-evidence" not in str(result)
    assert result["label"] == "Average customer"


def test_submit_cohort_review_returns_lifecycle_guidance():
    version_resp = {
        "acp_cohort_id": "acpc_1",
        "acp_cohort_version_id": "acpcv_1", "version": 1,
        "status": "DRAFT", "members": []}

    async def fake_request(method, base_url, path, **kwargs):
        return _response(method, path, version_resp)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_submit_acp_cohort_for_review(
            {"cohort_id": "acpc_1", "version_number": 1}, _ctx()))
    assert result["info_code"] == "ACP_LIFECYCLE_INFO"
    assert "approve" in result["message"]
    # No approval was attempted.
    assert result.get("status") is None


def test_cross_tenant_id_maps_to_opaque_not_found():
    async def fake_request(method, base_url, path, **kwargs):
        return _response(method, path, {
            "code": "ACP_INVALID_STATE",
            "reason_code": "NOT_FOUND",
            "detail": "cohort not found"}, status_code=404)

    with patch.object(acp_tools.core_client, "_request",
                      side_effect=fake_request):
        result = asyncio.run(_tool_get_acp_cohort(
            {"cohort_id": "acpc_foreign"}, _ctx()))
    assert result["error"]["code"] == "not_found"
    # No foreign-record disclosure: only the safe detail is passed.
    assert "foreign" not in result["error"]["message"]


def test_review_url_uses_gateway_public_origin():
    async def fake_request(method, base_url, path, **kwargs):
        return _response(method, path, {"acp_cohort_id": "acpc_1",
                                        "status": "ACTIVE"})

    with patch.object(acp_tools.settings, "GATEWAY_PUBLIC_URL",
                      "https://gateway.example.com"), \
            patch.object(acp_tools.core_client, "_request",
                         side_effect=fake_request):
        result = asyncio.run(_tool_get_acp_cohort(
            {"cohort_id": "acpc_1"}, _ctx()))
    assert result["review_url"] == (
        "https://gateway.example.com/api/v2/crm/acp/cohorts/console")


def test_tool_results_never_carry_evidence_bodies():
    """Member projections strip raw evidence fields."""
    member = {
        "organization_id": "org_1",
        "canonical_legal_name": "Alpha",
        "country_code": "IT",
        "decision": "INCLUDED",
        "weight": "1.000",
        "identity_resolution_status": "RESOLVED",
        "evidence_status": "COMPLETE",
        "freshness_status": "FRESH",
        "provenance": "PROPOSED",
        "accepted_observation_snapshot": {"observations": ["secret"]},
        "source_observation_ids": ["obs_1", "obs_2"],
    }
    view = acp_tools._member_min_view(member)
    assert "accepted_observation_snapshot" not in view
    assert "source_observation_ids" not in view
    assert "secret" not in str(view)