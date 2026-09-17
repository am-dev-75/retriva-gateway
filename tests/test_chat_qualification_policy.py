"""Chat policy contract tests: real loop/tools, mocked model and CRM transport.

Scripted model responses test orchestration, not natural-language compliance.
The separate live strict-chat acceptance is required to validate the latter.
No workbook parsing or candidate research decisions belong in these tests.
"""
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from retriva_gateway.agent.loop import AGENT_SYSTEM_PROMPT
from retriva_gateway.agent.tools import build_default_tool_registry
from retriva_gateway.api.v2.chat import _agent_chat
from retriva_gateway.core.models import ChatRequest


def response(tool=None, args=None, content=""):
    message = {"role": "assistant", "content": content}
    if tool:
        message["tool_calls"] = [{"id": f"call_{tool}", "type": "function",
                                  "function": {"name": tool, "arguments": json.dumps(args or {})}}]
    return {"choices": [{"message": message}]}


def readiness(capability="IDENTITY_ONLY", blocker=None):
    return {
        "status": "not_ready" if blocker else "ok",
        "qualification_readiness": not blocker,
        "blocking_reasons": [blocker] if blocker else [],
        "global_acp": {"found": blocker != "GLOBAL_ACP_UNAVAILABLE"},
        "global_cco": {"found": blocker != "GLOBAL_CCO_UNAVAILABLE"},
        "web_research": {"public_research_ready": True, "qualification_can_proceed": True,
                         "search_providers": [{"kind": "searxng", "search_capability": capability}]},
        "warnings": ["External discovery degraded"] if capability != "GENERAL_WEB" else [],
    }


def run_chat(responses, ready, *, attachments=None, message="Qualify the attached workbook.", fail_post=False):
    requests = []
    tool_results = []
    snapshots = []
    replies = iter(responses)

    async def model(payload, stream=False):
        snapshots.append(json.loads(json.dumps(payload)))
        tool_results[:] = [json.loads(m["content"]) for m in payload["messages"] if m["role"] == "tool"]
        return next(replies)

    async def transport(method, base_url, path, **kwargs):
        requests.append((method, path, kwargs))
        req = httpx.Request(method, base_url + path)
        if (method, path) == ("GET", "/api/v2/crm/readiness"):
            data = ready
        elif (method, path) == ("POST", "/api/v2/crm/qualify"):
            if fail_post:
                error = httpx.Response(503, request=req, json={"detail": "qualification service unavailable"})
                error.raise_for_status()
            data = {"status": "accepted", "job_id": "job_chat", **kwargs["json"]}
        else:
            raise AssertionError(f"Unexpected request {method} {path}")
        return httpx.Response(200, request=req, json=data)

    req = ChatRequest(message=message, session_id="sess_new", tools_enabled=True,
                      attachment_ids=["att_new"] if attachments is None else attachments, stream=False)
    with patch("retriva_gateway.agent.loop.core_client.chat_completions", AsyncMock(side_effect=model)), \
         patch("retriva_gateway.agent.tools.core_client._request", AsyncMock(side_effect=transport)), \
         patch("retriva_gateway.agent.loop.settings.AGENT_TOOL_ALLOWLIST", []):
        reply = asyncio.run(_agent_chat(req, "test-correlation"))
    assert reply.status_code == 200
    return json.loads(reply.body), requests, tool_results, snapshots


def starts():
    return [response("get_qualification_readiness"),
            response("qualify_candidates", {"attachment_id": "att_new"}),
            response(content="Started job_chat; research warnings will be reported by the workflow.")]


@pytest.mark.parametrize("capability,workbook", [
    ("GENERAL_WEB", "a workbook"),
    ("IDENTITY_ONLY", "a workbook with verified websites"),
    ("IDENTITY_ONLY", "a workbook whose contents have not yet been parsed"),
    ("IDENTITY_ONLY", "a mixed workbook with supplied sites and externally dependent candidates"),
])
def test_requested_workbooks_invoke_official_tool(capability, workbook):
    ready = readiness(capability)
    reply, requests, results, snapshots = run_chat(starts(), ready, message=f"Qualify {workbook} attached here.")
    assert [(r[0], r[1]) for r in requests] == [
        ("GET", "/api/v2/crm/readiness"), ("POST", "/api/v2/crm/qualify")]
    assert requests[1][2]["json"] == {"session_id": "sess_new", "attachment_id": "att_new", "kb_id": "default"}
    assert results[0] == ready  # warnings and capability survive unchanged
    assert results[1]["job_id"] == "job_chat"
    assert reply["agent"]["tool_calls"][-1]["ok"] is True
    assert "GENERAL_WEB degradation alone is NOT a job-level blocker" in snapshots[0]["messages"][0]["content"]
    assert "workflow owns workbook parsing" in AGENT_SYSTEM_PROMPT
    # The API's existing default is conversational context, not ACP/CCO selection.
    assert snapshots[0]["kb_ids"] == ["default"]
    descriptions = {t["function"]["name"]: t["function"]["description"] for t in snapshots[0]["tools"]}
    assert "GENERAL_WEB degradation alone is not a" in descriptions["get_qualification_readiness"]
    assert "VERIFIED_DOMAIN_RESEARCH" in descriptions["qualify_candidates"]


@pytest.mark.parametrize("blocker", ["GLOBAL_ACP_UNAVAILABLE", "GLOBAL_CCO_UNAVAILABLE"])
def test_missing_global_profile_reports_blocker_without_starting(blocker):
    reply, requests, results, _ = run_chat([
        response("get_qualification_readiness"), response(content=f"Cannot start: {blocker}")], readiness(blocker=blocker))
    assert blocker in results[0]["blocking_reasons"]
    assert blocker in reply["content"]
    assert all(r[0] == "GET" for r in requests)
    assert "no active usable global ACP or authoritative" in AGENT_SYSTEM_PROMPT


def test_missing_attachment_cannot_start_even_if_model_invents_one():
    reply, requests, results, _ = run_chat([
        response("qualify_candidates", {"attachment_id": "invented"}),
        response(content="Please attach a supported workbook.")], readiness(), attachments=[])
    assert requests == []
    assert results[0]["error"]["code"] == "missing_attachment"
    assert reply["agent"]["tool_calls"][0]["ok"] is False
    assert "attach" in reply["content"]


def test_qualification_service_unavailable_reported():
    scripted = starts()[:2] + [response(content="Qualification service unavailable; no job started.")]
    reply, requests, results, _ = run_chat(scripted, readiness(), fail_post=True)
    assert results[-1]["error"]["code"] == "upstream_error"
    assert "503" in results[-1]["error"]["message"]
    assert "unavailable" in reply["content"]
    assert reply["agent"]["tool_calls"][-1]["ok"] is False
    assert sum(r[0] == "POST" for r in requests) == 1


def test_unchanged_strict_harness_detects_real_tool_execution():
    # Optional sibling integration: no copy or modification of harness code.
    path = Path(__file__).resolve().parents[2] / "retriva-local-containerized-deployment/scripts/e2e_qualify.py"
    if not path.exists():
        pytest.skip("Sibling deployment repository required for harness integration")
    spec = importlib.util.spec_from_file_location("qualification_policy_harness", path)
    harness = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = harness
    spec.loader.exec_module(harness)
    reply, requests, _, _ = run_chat(starts(), readiness())

    class ChatTransport:
        def post_json(self, url, payload):
            assert url == "http://gateway/gateway/chat"
            assert payload["tools_enabled"] is True
            assert "kb_ids" not in payload
            return 200, json.dumps(reply).encode()

    request = harness.build_chat_request("sess_new", "Qualify workbook", ["att_new"], None)
    _, invocation = harness.trigger_via_chat(ChatTransport(), "http://gateway", request, None)
    assert invocation["tool"] == "qualify_candidates" and invocation["ok"] is True
    assert requests[-1][2]["json"]["attachment_id"] == "att_new"


def test_chat_never_initiates_direct_fallback_after_refusal():
    reply, requests, _, _ = run_chat([
        response("get_qualification_readiness"), response(content="Cannot execute qualification.")], readiness())
    assert [r[1] for r in requests] == ["/api/v2/crm/readiness"]
    assert not any(t["tool"] == "qualify_candidates" for t in reply["agent"]["tool_calls"])
    assert "direct-mode" in AGENT_SYSTEM_PROMPT
    assert all("direct" not in name for name in build_default_tool_registry().names())
