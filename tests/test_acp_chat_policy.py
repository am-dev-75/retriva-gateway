"""ACP chat-policy contract tests (Spec 020): real loop/tools, mocked
model and CRM transport (pattern of test_chat_qualification_policy.py).

Scripted model responses test orchestration, not natural-language
compliance; the deployed live acceptance validates the latter.  Covers
the governing deterministic scenarios: proposal-only authorization on
extrapolation requests, no automatic generation/approval/activation,
no generic grounding refusal, KB-independence, no tenant/tag arguments,
Qdrant/SQLite untouched, typed errors never converted to KB
insufficiency, activation/rollback wording boundaries, and review-URL
presentation.
"""
import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from retriva_gateway.agent.loop import AGENT_SYSTEM_PROMPT
from retriva_gateway.agent.tools import build_default_tool_registry
from retriva_gateway.api.v2.chat import _agent_chat
from retriva_gateway.core.models import ChatRequest

ACP_BASE = "/api/v2/crm/acp"


def response(tool=None, args=None, content=""):
    message = {"role": "assistant", "content": content}
    if tool:
        message["tool_calls"] = [{
            "id": f"call_{tool}", "type": "function",
            "function": {"name": tool,
                         "arguments": json.dumps(args or {})}}]
    return {"choices": [{"message": message}]}


def acp_transport(paths):
    """Fake CRM transport serving the given ACP paths.  A path value may
    be ``(data, status)``; non-2xx raises like the real client."""
    calls = []

    async def transport(method, base_url, path, **kwargs):
        calls.append((method, path, kwargs))
        req = httpx.Request(method, base_url + path)
        data = paths.get((method, path))
        assert data is not None, f"Unexpected request {method} {path}"
        status = 200
        if isinstance(data, tuple):
            data, status = data
        resp = httpx.Response(status, request=req, json=data)
        if status >= 400:
            resp.raise_for_status()
        return resp

    return transport, calls


PROPOSAL = {
    "acp_cohort_id": "acpc_chat",
    "status": "ACTIVE",
    "current_version": 1,
    "policy_version": "pol_abc",
    "counts": {"included": 0, "excluded": 1, "pending_review": 2,
               "outlier": 0, "insufficient_data": 0},
    "proposal_counts": {"considered": 3, "proposed_now": 2,
                        "excluded_recorded_now": 1, "cap_skipped": 0},
}
VERSION = {
    "acp_cohort_id": "acpc_chat",
    "acp_cohort_version_id": "acpcv_chat",
    "version": 1, "status": "DRAFT",
    "members": [
        {"organization_id": "org_1", "canonical_legal_name": "Alpha",
         "country_code": "IT", "decision": "PENDING_REVIEW",
         "identity_resolution_status": "RESOLVED",
         "freshness_status": "FRESH"},
        {"organization_id": "org_2", "canonical_legal_name": "Beta",
         "country_code": "DE", "decision": "EXCLUDED",
         "identity_resolution_status": "RESOLVED",
         "freshness_status": "FRESH"},
    ],
}


def run_chat(responses, paths, *, message, attachments=None, kb_ids=None,
             allowlist=None, session_id="sess_acp"):
    replies = iter(responses)
    model_snapshots = []

    async def model(payload, stream=False):
        model_snapshots.append(json.loads(json.dumps(payload)))
        return next(replies)

    transport, calls = acp_transport(paths)
    req = ChatRequest(message=message, session_id=session_id,
                      tools_enabled=True if session_id else False,
                      attachment_ids=list(attachments or []),
                      kb_ids=list(kb_ids or ["default"]),
                      stream=False)
    with patch("retriva_gateway.agent.loop.core_client.chat_completions",
               AsyncMock(side_effect=model)), \
         patch("retriva_gateway.agent.tools.core_client._request",
               AsyncMock(side_effect=transport)), \
         patch("retriva_gateway.agent.tools.settings.GATEWAY_PUBLIC_URL",
               "http://gateway.test"), \
         patch("retriva_gateway.agent.loop.settings.AGENT_TOOL_ALLOWLIST",
               allowlist or []):
        reply = asyncio.run(_agent_chat(req, "test-correlation-acp"))
    assert reply.status_code == 200
    return json.loads(reply.body), calls, model_snapshots


PROPOSAL_PATHS = {
    ("POST", f"{ACP_BASE}/cohorts"): PROPOSAL,
    ("GET", f"{ACP_BASE}/cohorts/acpc_chat/versions/1"): VERSION,
}
PROPOSAL_REPLIES = [
    response("propose_acp_cohort", {"name": "Active customers"}),
    response(content="The draft cohort proposal is ready for review. "
                     "Nothing has been approved, generated, or "
                     "activated."),
]


def test_extrapolation_request_invokes_propose_only():
    """A1 + A2: extrapolate -> propose_acp_cohort; NO generation,
    approval, or activation calls."""
    reply, calls, snapshots = run_chat(
        PROPOSAL_REPLIES, PROPOSAL_PATHS,
        message="Extrapolate the Average Customer Profile from our "
                "customers.")
    crm_calls = [(m, p) for m, p, _ in calls]
    assert ("POST", f"{ACP_BASE}/cohorts") in crm_calls
    forbidden = ("/approve", "/activate", "/rollback", "/submit-review",
                 f"{ACP_BASE}/generation-runs")
    assert not any(any(f in p for f in forbidden) for _, p in crm_calls)
    # The model never generated SQL and never saw a tenant argument.
    for _, _, kwargs in calls:
        body = kwargs.get("json") or {}
        assert "tenant_id" not in body
        assert "sql" not in json.dumps(body).lower()
    tool_results = [json.loads(m["content"])
                    for m in snapshots[1]["messages"]
                    if m["role"] == "tool"]
    proposal = tool_results[0]
    assert proposal["cohort_id"] == "acpc_chat"
    assert proposal["cohort_version_id"] == "acpcv_chat"
    assert proposal["review_url"].startswith(
        "http://gateway.test/api/v2/crm/acp/cohorts/console")


def test_empty_kb_does_not_produce_grounding_refusal():
    """A3: with the ACP tools available, an extrapolation request on an
    empty/absent KB invokes the workflow tool instead of a grounding
    refusal."""
    reply, calls, _ = run_chat(
        PROPOSAL_REPLIES, PROPOSAL_PATHS,
        message="Extrapolate the ACP from our customers.",
        kb_ids=[], attachments=[])
    assert ("POST", f"{ACP_BASE}/cohorts") in [(m, p) for m, p, _ in calls]


def test_selected_kb_does_not_alter_proposal_arguments():
    """A4: changing the selected KB does not alter the proposal
    arguments (no KB parameter exists on the tool; the payload is
    identical)."""
    _, calls_default, _ = run_chat(
        PROPOSAL_REPLIES, PROPOSAL_PATHS,
        message="Extrapolate the ACP.", kb_ids=["default"])
    _, calls_other, _ = run_chat(
        PROPOSAL_REPLIES, PROPOSAL_PATHS,
        message="Extrapolate the ACP.", kb_ids=["other-kb"])
    def payload_of(calls):
        return [(p, kw.get("json"))
                for m, p, kw in calls if m == "POST"]
    assert payload_of(calls_default) == payload_of(calls_other)


def test_metadata_tag_never_enters_tool_arguments():
    """A5: dept_sales_potential_customer never appears in tool calls."""
    _, calls, snapshots = run_chat(
        PROPOSAL_REPLIES, PROPOSAL_PATHS,
        message="Extrapolate the ACP from our dept_sales_potential_"
                "customer tagged companies.")
    for _, _, kwargs in calls:
        assert "dept_sales_potential_customer" not in json.dumps(
            kwargs.get("json") or {})
    assert all("dept_sales_potential_customer"
               not in json.dumps(t.get("function", {}).get("parameters", {}))
               for t in snapshots[0]["tools"])


def test_acp_tools_never_touch_qdrant_or_sqlite():
    """A6 + A7: the transport sees ONLY CRM API paths — no Qdrant, no
    KB reads, no legacy stores."""
    _, calls, _ = run_chat(
        PROPOSAL_REPLIES, PROPOSAL_PATHS,
        message="Extrapolate the ACP.")
    for _, path, _ in calls:
        assert path.startswith(ACP_BASE)
    # The prompt forbids the legacy influences explicitly.
    assert "Qdrant metadata" in AGENT_SYSTEM_PROMPT
    assert "legacy SQLite" in AGENT_SYSTEM_PROMPT


def test_typed_errors_are_not_converted_to_kb_insufficiency():
    """A21: an upstream typed failure surfaces as a typed tool result."""
    error_paths = {
        ("POST", f"{ACP_BASE}/cohorts"): (
            {"code": "ACP_PERMISSION_DENIED",
             "detail": "actor is not authorized"}, 403),
    }
    replies = [
        response("propose_acp_cohort", {"name": "Active customers"}),
        response(content="The ACP workflow reported permission_denied."),
    ]
    reply, calls, snapshots = run_chat(
        replies, error_paths,
        message="Extrapolate the ACP.")
    tool_results = [json.loads(m["content"])
                    for m in snapshots[1]["messages"]
                    if m["role"] == "tool"]
    assert tool_results[0]["error"]["code"] == "permission_denied"
    # The loop continued (no crash) and the final answer acknowledges
    # the typed failure rather than a KB insufficiency.
    assert reply["agent"]["tool_calls"][-1]["ok"] is False


def test_activation_wording_is_never_inferred():
    """A18 + A19: create/generate/extrapolate/rebuild wording never
    invokes activate_acp or rollback; the prompt forbids inference."""
    reply, calls, snapshots = run_chat(
        PROPOSAL_REPLIES, PROPOSAL_PATHS,
        message="Create (rebuild) the ACP from our customers.")
    assert not any("/activate" in p or "/rollback" in p
                   for _, p, _ in calls)
    assert "Never infer activation intent" in AGENT_SYSTEM_PROMPT
    destructive = {t["function"]["name"]
                   for t in snapshots[0]["tools"]
                   if t["function"]["name"] in
                   ("activate_acp", "rollback_acp_activation",
                    "approve_acp", "approve_acp_cohort")}
    # The tools exist and are flagged destructive in the registry.
    registry = build_default_tool_registry()
    for name in destructive:
        assert registry.get(name).destructive is True


def test_allowlist_limits_acp_tool_availability():
    """Deployments with AGENT_TOOL_ALLOWLIST must opt in explicitly."""
    restricted = run_chat(
        PROPOSAL_REPLIES, PROPOSAL_PATHS,
        message="Extrapolate the ACP.",
        allowlist=["propose_acp_cohort",
                   "get_qualification_readiness"])[2]
    exposed = {t["function"]["name"] for t in restricted[0]["tools"]}
    assert "propose_acp_cohort" in exposed
    assert "activate_acp" not in exposed


def test_prompt_policy_block_present():
    """The governing chat policy (rules 1–12) is encoded in the prompt."""
    required = [
        "propose_acp_cohort",
        "knowledge-base insufficiency",
        "PostgreSQL business workflow",
        "dept_sales_potential_customer",
        "PROPOSAL ONLY",
        "SEPARATE explicit user request",
        "Never infer activation intent",
        "review URL",
        "never company evidence bodies",
        "reason codes, hashes, opaque IDs",
        "never generate SQL",
        "never bypass a typed failure",
    ]
    lowered = " ".join(AGENT_SYSTEM_PROMPT.lower().split())
    for fragment in required:
        assert fragment.lower() in lowered, fragment


def test_workflow_intent_routes_to_agent_loop_without_optin():
    """A CRM-workflow message reaches the agent loop even when the
    client did not opt in (no session_id, no tools_enabled); ordinary
    knowledge questions keep the plain RAG path."""
    from retriva_gateway.api.v2.chat import _run_agent_mode
    workflow = ChatRequest(message="Propose a new ACP reference cohort "
                                   "from the active customers",
                           session_id=None, tools_enabled=False,
                           kb_ids=["default"], stream=False)
    knowledge = ChatRequest(message="What is the return policy in the "
                                    "documentation?",
                            session_id=None, tools_enabled=False,
                            kb_ids=["default"], stream=False)
    assert _run_agent_mode(workflow, "corr-route") is not None
    assert _run_agent_mode(knowledge, "corr-route") is None
    # Explicit opt-in keeps working.
    opted_in = ChatRequest(message="hello", session_id="s1",
                           tools_enabled=True, kb_ids=["default"],
                           stream=False)
    assert _run_agent_mode(opted_in, "corr-route") is not None
    # Streaming never enters agent mode.
    streaming = ChatRequest(message="Propose a new ACP reference cohort",
                            session_id=None, tools_enabled=False,
                            kb_ids=["default"], stream=True)
    assert _run_agent_mode(streaming, "corr-route") is None


def test_workflow_chat_synthesizes_session_attribution():
    """Without a client session, the loop attributes the turn to a
    session derived from the correlation id (never an empty actor)."""
    reply, calls, snapshots = run_chat(
        PROPOSAL_REPLIES, PROPOSAL_PATHS,
        message="Propose a new ACP reference cohort from the active "
                "customers.",
        session_id=None)
    tool_results = [json.loads(m["content"])
                    for m in snapshots[1]["messages"]
                    if m["role"] == "tool"]
    assert tool_results[0]["cohort_id"] == "acpc_chat"
    posts = [(kw.get("json") or {})
             for method, _, kw in calls if method == "POST"]
    assert posts and posts[0].get("actor_id") == \
        "chat:sess_test-correlation-acp"