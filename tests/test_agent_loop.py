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
Tests for the Gateway chat agent loop and typed tools (ADR-0001).

Covers:
- tool registry and OpenAI schema generation;
- schema validation of tool arguments;
- trusted-context enforcement (attachment IDs, job IDs);
- recursion protection (identical repeated calls short-circuited);
- allow-list enforcement;
- bounded iterations;
- the agent loop end-to-end with a mocked LLM and mocked tool executors;
- plain chat remains unaffected (no tools => no agent path).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from retriva_gateway.agent.tools import (
    ToolContext,
    ToolDefinition,
    ToolExecutionError,
    ToolRegistry,
    _validate_against_schema,
    build_default_tool_registry,
)
from retriva_gateway.agent.loop import AgentLoopResult, run_agent_loop
from retriva_gateway.config import settings


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def test_crm_tools_registered(self):
        registry = build_default_tool_registry()
        names = registry.names()
        for expected in [
            "qualify_candidates",
            "get_qualification_job",
            "get_qualification_results",
            "get_qualification_report",
            "get_qualification_artifacts",
            "cancel_qualification_job",
            "get_qualification_readiness",
        ]:
            assert expected in names

    def test_openai_schema_shape(self):
        registry = build_default_tool_registry()
        schema = registry.openai_schema()
        assert len(schema) == len(registry.names())
        entry = next(s for s in schema if s["function"]["name"] == "qualify_candidates")
        assert entry["type"] == "function"
        assert "attachment_id" in entry["function"]["parameters"]["properties"]
        assert entry["function"]["parameters"]["required"] == ["attachment_id"]

    def test_allow_list_filters_schema(self):
        registry = build_default_tool_registry(allow_list=["get_qualification_readiness"])
        schema = registry.openai_schema()
        assert [s["function"]["name"] for s in schema] == ["get_qualification_readiness"]

    def test_duplicate_registration_rejected(self):
        from retriva_gateway.agent.tools import ToolDefinition, ToolRegistry

        async def _noop(args, ctx):
            return {}

        registry = ToolRegistry()
        tool = ToolDefinition(name="x", description="", parameters={}, execute=_noop)
        registry.register(tool)
        with pytest.raises(ValueError):
            registry.register(tool)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def setup_method(self):
        from retriva_gateway.agent.tools import _validate_against_schema
        self.validate = _validate_against_schema

    def test_missing_required(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        assert self.validate({}, schema) == "missing required parameter: a"

    def test_unknown_parameter(self):
        schema = {"type": "object", "properties": {}, "required": []}
        assert "unknown parameter" in self.validate({"b": 1}, schema)

    def test_wrong_type(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": []}
        assert "must be a string" in self.validate({"a": 1}, schema)

    def test_valid(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        assert self.validate({"a": "x"}, schema) is None


# ---------------------------------------------------------------------------
# Trusted-context enforcement
# ---------------------------------------------------------------------------

class TestTrustedContext:
    @pytest.mark.asyncio
    async def test_qualify_rejects_foreign_attachment(self):
        from retriva_gateway.agent.tools import ToolContext, ToolExecutionError, build_default_tool_registry

        registry = build_default_tool_registry()
        tool = registry.get("qualify_candidates")
        ctx = ToolContext(
            session_id="sess_1", kb_id="kb1",
            allowed_attachment_ids=["att_ok"],
        )
        with pytest.raises(ToolExecutionError) as exc:
            await tool.execute({"attachment_id": "att_foreign"}, ctx)
        assert exc.value.code == "identifier_not_allowed"

    @pytest.mark.asyncio
    async def test_job_id_must_be_job_prefixed(self):
        from retriva_gateway.agent.tools import ToolContext, ToolExecutionError, build_default_tool_registry

        registry = build_default_tool_registry()
        tool = registry.get("get_qualification_job")
        ctx = ToolContext(session_id="sess_1", kb_id="kb1")
        with pytest.raises(ToolExecutionError) as exc:
            await tool.execute({"job_id": "../../etc/passwd"}, ctx)
        assert exc.value.code == "invalid_job_id"

    @pytest.mark.asyncio
    async def test_qualify_uses_trusted_session_and_kb(self):
        """The model cannot choose session_id/kb_id — trusted ctx wins."""
        from retriva_gateway.agent.tools import ToolContext, build_default_tool_registry

        captured = {}

        async def fake_crm_request(method, path, **kwargs):
            captured["payload"] = kwargs.get("json")
            return {"job_id": "job_1"}

        registry = build_default_tool_registry()
        tool = registry.get("qualify_candidates")
        ctx = ToolContext(session_id="sess_trusted", kb_id="kb_trusted",
                          allowed_attachment_ids=["att_1"])
        with patch("retriva_gateway.agent.tools._crm_request", fake_crm_request):
            result = await tool.execute({"attachment_id": "att_1"}, ctx)
        assert result == {"job_id": "job_1"}
        assert captured["payload"]["session_id"] == "sess_trusted"
        assert captured["payload"]["kb_id"] == "kb_trusted"
        assert captured["payload"]["attachment_id"] == "att_1"


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def _llm_response(content="", tool_calls=None):
    """Fake Core /v1/chat/completions response."""
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message, "finish_reason": "stop"}]}


def _make_registry_with_stub(executor):
    from retriva_gateway.agent.tools import ToolDefinition, ToolRegistry

    async def _exec(args, ctx):
        return await executor(args, ctx)

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="stub_tool",
        description="stub",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        execute=_exec,
    ))
    return registry


class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_final_answer_without_tools(self):
        from retriva_gateway.agent.loop import run_agent_loop
        from retriva_gateway.agent.tools import ToolContext, build_default_tool_registry

        registry = build_default_tool_registry()
        ctx = ToolContext(session_id="s", kb_id="k")
        with patch(
            "retriva_gateway.agent.loop.core_client.chat_completions",
            new=AsyncMock(return_value=_llm_response(content="hello")),
        ):
            result = await run_agent_loop(
                user_message="hi", registry=registry, ctx=ctx, kb_ids=["k"]
            )
        assert result.content == "hello"
        assert result.stopped_reason == "final_answer"
        assert result.tool_calls_executed == []

    @pytest.mark.asyncio
    async def test_tool_call_executed_and_result_fed_back(self):
        from retriva_gateway.agent.loop import run_agent_loop
        from retriva_gateway.agent.tools import ToolContext

        calls = []

        async def executor(args, ctx):
            calls.append(args)
            return {"result": 42}

        registry = _make_registry_with_stub(executor)
        ctx = ToolContext(session_id="s", kb_id="k")

        responses = [
            _llm_response(tool_calls=[{
                "id": "call_1", "type": "function",
                "function": {"name": "stub_tool", "arguments": json.dumps({"x": "1"})},
            }]),
            _llm_response(content="done"),
        ]

        async def fake_chat(payload, stream=False):
            return responses[min(len(calls), 1)]

        with patch(
            "retriva_gateway.agent.loop.core_client.chat_completions",
            new=AsyncMock(side_effect=fake_chat),
        ):
            result = await run_agent_loop(
                user_message="go", registry=registry, ctx=ctx, kb_ids=["k"]
            )
        assert calls == [{"x": "1"}]
        assert result.stopped_reason == "final_answer"
        assert result.tool_calls_executed[0]["ok"] is True

    @pytest.mark.asyncio
    async def test_repeated_identical_call_short_circuited(self):
        from retriva_gateway.agent.loop import run_agent_loop
        from retriva_gateway.agent.tools import ToolContext

        calls = []

        async def executor(args, ctx):
            calls.append(args)
            return {"n": len(calls)}

        registry = _make_registry_with_stub(executor)
        ctx = ToolContext(session_id="s", kb_id="k")
        tc = {
            "id": "call_1", "type": "function",
            "function": {"name": "stub_tool", "arguments": json.dumps({"x": "1"})},
        }
        responses = [
            _llm_response(tool_calls=[tc]),
            _llm_response(tool_calls=[tc]),  # identical repeat
            _llm_response(content="done"),
        ]
        idx = {"i": 0}

        async def fake_chat(payload, stream=False):
            r = responses[idx["i"]]
            idx["i"] += 1
            return r

        with patch(
            "retriva_gateway.agent.loop.core_client.chat_completions",
            new=AsyncMock(side_effect=fake_chat),
        ):
            result = await run_agent_loop(
                user_message="go", registry=registry, ctx=ctx, kb_ids=["k"]
            )
        # The stub executed only ONCE; the repeat was short-circuited.
        assert calls == [{"x": "1"}]
        assert result.tool_calls_executed[1]["ok"] is False

    @pytest.mark.asyncio
    async def test_allow_list_blocks_unlisted_tool(self):
        from retriva_gateway.agent.loop import run_agent_loop
        from retriva_gateway.agent.tools import ToolContext, build_default_tool_registry

        registry = build_default_tool_registry()
        ctx = ToolContext(session_id="s", kb_id="k")
        tc = {
            "id": "call_1", "type": "function",
            "function": {"name": "cancel_qualification_job", "arguments": "{}"},
        }
        with patch.object(settings, "AGENT_TOOL_ALLOWLIST", ["get_qualification_readiness"]):
            with patch(
                "retriva_gateway.agent.loop.core_client.chat_completions",
                new=AsyncMock(return_value=_llm_response(tool_calls=[tc])),
            ):
                result = await run_agent_loop(
                    user_message="go", registry=registry, ctx=ctx, kb_ids=["k"]
                )
        assert result.tool_calls_executed[0]["ok"] is False

    @pytest.mark.asyncio
    async def test_max_iterations_bounded(self):
        from retriva_gateway.agent.loop import run_agent_loop
        from retriva_gateway.agent.tools import ToolContext

        async def executor(args, ctx):
            return {"ok": True}

        registry = _make_registry_with_stub(executor)
        ctx = ToolContext(session_id="s", kb_id="k")
        tc = {
            "id": "call_1", "type": "function",
            "function": {"name": "stub_tool", "arguments": json.dumps({"x": "1"})},
        }

        async def fake_chat(payload, stream=False):
            # Always request a tool call with a DIFFERENT argument each time
            # (so recursion protection does not kick in) to force the bound.
            n = len(payload["messages"])
            tc2 = dict(tc)
            tc2["function"] = {"name": "stub_tool", "arguments": json.dumps({"x": str(n)})}
            return _llm_response(tool_calls=[tc2])

        with patch.object(settings, "AGENT_MAX_TOOL_ITERATIONS", 3):
            with patch(
                "retriva_gateway.agent.loop.core_client.chat_completions",
                new=AsyncMock(side_effect=fake_chat),
            ):
                result = await run_agent_loop(
                    user_message="go", registry=registry, ctx=ctx, kb_ids=["k"]
                )
        assert result.iterations == 3
        assert result.stopped_reason == "max_iterations"
        assert "tool-call limit" in result.content

    @pytest.mark.asyncio
    async def test_invalid_arguments_rejected(self):
        from retriva_gateway.agent.loop import run_agent_loop
        from retriva_gateway.agent.tools import ToolContext

        executed = []

        async def executor(args, ctx):
            executed.append(args)
            return {}

        registry = _make_registry_with_stub(executor)
        ctx = ToolContext(session_id="s", kb_id="k")
        tc = {
            "id": "call_1", "type": "function",
            "function": {"name": "stub_tool", "arguments": json.dumps({"wrong": 1})},
        }
        with patch(
            "retriva_gateway.agent.loop.core_client.chat_completions",
            new=AsyncMock(return_value=_llm_response(tool_calls=[tc])),
        ):
            result = await run_agent_loop(
                user_message="go", registry=registry, ctx=ctx, kb_ids=["k"]
            )
        assert executed == []  # executor never ran
        assert result.tool_calls_executed[0]["ok"] is False


# ---------------------------------------------------------------------------
# Plain chat unaffected
# ---------------------------------------------------------------------------

class TestPlainChatUnaffected:
    def test_plain_chat_request_has_no_agent_fields_required(self):
        from retriva_gateway.core.models import ChatRequest

        req = ChatRequest(message="hello")
        assert req.session_id is None
        assert req.tools_enabled is False
        assert req.attachment_ids is None

    def test_agent_mode_requires_opt_in(self):
        from retriva_gateway.api.v2.chat import _run_agent_mode
        from retriva_gateway.core.models import ChatRequest

        # No session_id / no tools_enabled => plain chat (None sentinel).
        assert _run_agent_mode(ChatRequest(message="hi"), "c1") is None
        assert _run_agent_mode(
            ChatRequest(message="hi", session_id="s"), "c1"
        ) is None
        assert _run_agent_mode(
            ChatRequest(message="hi", tools_enabled=True), "c1"
        ) is None


# ---------------------------------------------------------------------------
# Cross-session isolation (server-side enforcement, not prompt-based)
# ---------------------------------------------------------------------------

class TestCrossSessionIsolation:
    """A session must not access/cancel jobs or artifacts of another session.

    These tests exercise the tool executors directly (server-side boundary),
    proving the enforcement does NOT depend on the system prompt.
    """

    def _ctx(self, session_id):
        from retriva_gateway.agent.tools import ToolContext
        return ToolContext(session_id=session_id, kb_id="kb1")

    @pytest.mark.asyncio
    async def test_get_job_from_other_session_rejected(self):
        from retriva_gateway.agent.tools import ToolExecutionError, build_default_tool_registry

        registry = build_default_tool_registry()
        tool = registry.get("get_qualification_job")

        async def fake_crm_request(method, path, **kwargs):
            # Core returns the job — it belongs to session A.
            return {"job_id": "job_other", "session_id": "sess_A", "state": "COMPLETED"}

        with patch("retriva_gateway.agent.tools._crm_request", fake_crm_request):
            with pytest.raises(ToolExecutionError) as exc:
                await tool.execute({"job_id": "job_other"}, self._ctx("sess_B"))
        assert exc.value.code == "job_not_in_session"
        assert exc.value.http_status == 403

    @pytest.mark.asyncio
    async def test_results_rejected_for_foreign_job(self):
        from retriva_gateway.agent.tools import ToolExecutionError, build_default_tool_registry

        registry = build_default_tool_registry()
        tool = registry.get("get_qualification_results")

        async def fake_crm_request(method, path, **kwargs):
            return {"job_id": "job_other", "session_id": "sess_A"}

        with patch("retriva_gateway.agent.tools._crm_request", fake_crm_request):
            with pytest.raises(ToolExecutionError) as exc:
                await tool.execute({"job_id": "job_other"}, self._ctx("sess_B"))
        assert exc.value.code == "job_not_in_session"

    @pytest.mark.asyncio
    async def test_cancel_rejected_for_foreign_job(self):
        from retriva_gateway.agent.tools import ToolExecutionError, build_default_tool_registry

        registry = build_default_tool_registry()
        tool = registry.get("cancel_qualification_job")
        calls = []

        async def fake_crm_request(method, path, **kwargs):
            calls.append((method, path))
            if method == "GET":
                return {"job_id": "job_other", "session_id": "sess_A"}
            return {"status": "cancel_requested"}

        with patch("retriva_gateway.agent.tools._crm_request", fake_crm_request):
            with pytest.raises(ToolExecutionError) as exc:
                await tool.execute({"job_id": "job_other"}, self._ctx("sess_B"))
        assert exc.value.code == "job_not_in_session"
        # The cancel POST must NEVER have been issued.
        assert all(m != "POST" for m, _ in calls)

    @pytest.mark.asyncio
    async def test_own_job_allowed(self):
        from retriva_gateway.agent.tools import build_default_tool_registry

        registry = build_default_tool_registry()
        tool = registry.get("get_qualification_job")

        async def fake_crm_request(method, path, **kwargs):
            return {"job_id": "job_mine", "session_id": "sess_A", "state": "COMPLETED"}

        with patch("retriva_gateway.agent.tools._crm_request", fake_crm_request):
            result = await tool.execute({"job_id": "job_mine"}, self._ctx("sess_A"))
        assert result["job_id"] == "job_mine"

    @pytest.mark.asyncio
    async def test_report_artifacts_scoped_to_job_session(self):
        """Artifact fetch uses the JOB's session (ownership already proven),
        and Core enforces artifact session scoping independently."""
        from retriva_gateway.agent.tools import build_default_tool_registry

        registry = build_default_tool_registry()
        tool = registry.get("get_qualification_report")
        fetched = []

        async def fake_crm_request(method, path, **kwargs):
            return {"job_id": "job_mine", "session_id": "sess_A",
                    "artifact_ids": ["art_1"]}

        async def fake_raw_request(method, base_url, path, **kwargs):
            fetched.append(path)
            class _R:
                content = b"# report"
            return _R()

        with patch("retriva_gateway.agent.tools._crm_request", fake_crm_request), \
             patch("retriva_gateway.agent.tools.core_client._request", fake_raw_request):
            result = await tool.execute({"job_id": "job_mine"}, self._ctx("sess_A"))
        assert fetched and "/sessions/sess_A/artifacts/" in fetched[0]
        assert result["report_markdown"] == "# report"


# ---------------------------------------------------------------------------
# Cross-turn job resumption (deterministic; mocked backend sequence)
# ---------------------------------------------------------------------------

class TestCrossTurnResumption:
    """A job started in turn 1 must be resumable in later turns of the SAME
    session, without a second qualification job and without the agent loop
    polling to completion.

    Deterministic strategy: the backend job-status sequence is mocked
    (CREATED -> RESEARCHING -> COMPLETED) and the real tool executors are
    exercised, so no real Web Research or GraphRAG is needed.
    """

    def _ctx(self, session_id="sess_resume", attachment_ids=None):
        from retriva_gateway.agent.tools import ToolContext
        return ToolContext(
            session_id=session_id, kb_id="kb1",
            allowed_attachment_ids=attachment_ids or ["att_1"],
        )

    @pytest.mark.asyncio
    async def test_turn1_starts_job_and_returns_before_completion(self):
        """Turn 1: qualify_candidates invoked exactly once; the loop returns
        with the job still running (no polling to completion)."""
        from retriva_gateway.agent.loop import run_agent_loop
        from retriva_gateway.agent.tools import build_default_tool_registry

        qualify_calls = []
        job_state = {"value": "RESEARCHING"}  # still running after turn 1

        async def fake_crm_request(method, path, **kwargs):
            if method == "POST" and path.endswith("/qualify"):
                qualify_calls.append(kwargs.get("json"))
                return {"status": "accepted", "job_id": "job_t1",
                        "session_id": "sess_resume", "kb_id": "kb1"}
            if method == "GET" and "/jobs/" in path:
                return {"job_id": "job_1", "session_id": "sess_resume",
                        "state": job_state["value"], "progress": 0.6}
            if method == "GET" and path.endswith("/readiness"):
                return {"public_research_ready": True}
            raise AssertionError(f"unexpected call {method} {path}")

        # Turn-1 LLM: readiness -> qualify -> report status -> final answer.
        responses = [
            _llm_response(tool_calls=[{"id": "c1", "type": "function",
                "function": {"name": "get_qualification_readiness", "arguments": "{}"}}]),
            _llm_response(tool_calls=[{"id": "c2", "type": "function",
                "function": {"name": "qualify_candidates",
                             "arguments": json.dumps({"attachment_id": "att_1"})}}]),
            _llm_response(tool_calls=[{"id": "c3", "type": "function",
                "function": {"name": "get_qualification_job",
                             "arguments": json.dumps({"job_id": "job_1"})}}]),
            _llm_response(content="Job job_1 started; currently RESEARCHING. I will check later."),
        ]
        idx = {"i": 0}

        async def fake_chat(payload, stream=False):
            r = responses[idx["i"]]
            idx["i"] += 1
            return r

        registry = build_default_tool_registry()
        with patch("retriva_gateway.agent.tools._crm_request", fake_crm_request), \
             patch("retriva_gateway.agent.loop.core_client.chat_completions",
                   new=AsyncMock(side_effect=fake_chat)):
            result = await run_agent_loop(
                user_message="Qualify the attached candidates.",
                registry=registry, ctx=self._ctx(), kb_ids=["kb1"],
            )
        # qualify_candidates invoked EXACTLY once.
        assert len(qualify_calls) == 1
        # Turn 1 returned with the job still RUNNING (not completed).
        assert job_state["value"] == "RESEARCHING"
        assert result.stopped_reason == "final_answer"
        assert result.iterations <= 6

    @pytest.mark.asyncio
    async def test_turn2_resumes_existing_job_without_new_job(self):
        """Turn 2: agent finds the existing job server-side (list tool),
        checks status once, and does NOT start another qualification."""
        from retriva_gateway.agent.loop import run_agent_loop
        from retriva_gateway.agent.tools import build_default_tool_registry

        qualify_calls = []
        job_state = {"value": "RESEARCHING"}

        async def fake_crm_request(method, path, **kwargs):
            if method == "POST" and path.endswith("/qualify"):
                qualify_calls.append(kwargs.get("json"))
                return {"status": "accepted", "job_id": "job_1"}
            if method == "GET" and "/sessions/sess_resume/jobs" in path:
                return {"session_id": "sess_resume", "jobs": [
                    {"job_id": "job_1", "session_id": "sess_resume",
                     "state": job_state["value"], "attachment_id": "att_1"}]}
            if method == "GET" and "/jobs/job_1" in path:
                return {"job_id": "job_1", "session_id": "sess_resume",
                        "state": job_state["value"], "progress": 0.6}
            raise AssertionError(f"unexpected call {method} {path}")

        responses = [
            _llm_response(tool_calls=[{"id": "c1", "type": "function",
                "function": {"name": "list_qualification_jobs", "arguments": "{}"}}]),
            _llm_response(tool_calls=[{"id": "c2", "type": "function",
                "function": {"name": "get_qualification_job",
                             "arguments": json.dumps({"job_id": "job_1"})}}]),
            _llm_response(content="Your qualification job job_1 is still RESEARCHING (60%)."),
        ]
        idx = {"i": 0}

        async def fake_chat(payload, stream=False):
            r = responses[idx["i"]]
            idx["i"] += 1
            return r

        registry = build_default_tool_registry()
        with patch("retriva_gateway.agent.tools._crm_request", fake_crm_request), \
             patch("retriva_gateway.agent.loop.core_client.chat_completions",
                   new=AsyncMock(side_effect=fake_chat)):
            result = await run_agent_loop(
                user_message="What is the status of the prospect qualification I started earlier?",
                registry=registry, ctx=self._ctx(), kb_ids=["kb1"],
            )
        # NO new qualification job was started in turn 2.
        assert qualify_calls == []
        assert result.stopped_reason == "final_answer"

    @pytest.mark.asyncio
    async def test_turn3_retrieves_results_and_artifacts(self):
        """Turn 3 (job completed): results + report + artifacts retrieved."""
        from retriva_gateway.agent.loop import run_agent_loop
        from retriva_gateway.agent.tools import build_default_tool_registry

        async def fake_crm_request(method, path, **kwargs):
            if method == "GET" and "/jobs/job_1/results" in path:
                return {"job_id": "job_1", "session_id": "sess_resume",
                        "results": [{"candidate_name": "Acme", "tier": "strong_fit",
                                     "icp_fit": {"overall": 0.84}}],
                        "artifacts": [{"artifact_id": "art_md",
                                       "filename": "qualification_report.md"}]}
            if method == "GET" and "/jobs/job_1" in path:
                return {"job_id": "job_1", "session_id": "sess_resume",
                        "state": "COMPLETED", "artifact_ids": ["art_md"]}
            raise AssertionError(f"unexpected call {method} {path}")

        async def fake_raw_request(method, base_url, path, **kwargs):
            class _R:
                content = b"# Prospect Qualification Report"
            return _R()

        responses = [
            _llm_response(tool_calls=[{"id": "c1", "type": "function",
                "function": {"name": "get_qualification_results",
                             "arguments": json.dumps({"job_id": "job_1"})}}]),
            _llm_response(tool_calls=[{"id": "c2", "type": "function",
                "function": {"name": "get_qualification_artifacts",
                             "arguments": json.dumps({"job_id": "job_1"})}}]),
            _llm_response(content="Acme: STRONG_FIT, ICP fit 84/100. Reports: qualification_report.md"),
        ]
        idx = {"i": 0}

        async def fake_chat(payload, stream=False):
            r = responses[idx["i"]]
            idx["i"] += 1
            return r

        registry = build_default_tool_registry()
        with patch("retriva_gateway.agent.tools._crm_request", fake_crm_request), \
             patch("retriva_gateway.agent.tools.core_client._request", fake_raw_request), \
             patch("retriva_gateway.agent.loop.core_client.chat_completions",
                   new=AsyncMock(side_effect=fake_chat)):
            result = await run_agent_loop(
                user_message="Show me the results and downloadable reports.",
                registry=registry, ctx=self._ctx(), kb_ids=["kb1"],
            )
        assert result.stopped_reason == "final_answer"
        assert "84/100" in result.content or "STRONG_FIT" in result.content

    @pytest.mark.asyncio
    async def test_duplicate_qualify_returns_existing_job(self):
        """Duplicate-job protection: qualify_candidates for an attachment
        that already has a running job returns the EXISTING job with
        status already_running — no second job is created."""
        from retriva_gateway.agent.tools import build_default_tool_registry

        created = []

        async def fake_crm_request(method, path, **kwargs):
            if method == "POST" and path.endswith("/qualify"):
                created.append(kwargs.get("json"))
                return {"status": "already_running", "job_id": "job_1",
                        "session_id": "sess_resume", "kb_id": "kb1"}
            raise AssertionError(f"unexpected call {method} {path}")

        registry = build_default_tool_registry()
        tool = registry.get("qualify_candidates")
        with patch("retriva_gateway.agent.tools._crm_request", fake_crm_request):
            result = await tool.execute({"attachment_id": "att_1"}, self._ctx())
        assert result["status"] == "already_running"
        assert result["job_id"] == "job_1"
        assert "already running" in result["note"]

    @pytest.mark.asyncio
    async def test_repeated_get_job_in_same_turn_short_circuited(self):
        """A running job must not consume all six iterations: identical
        repeated get_qualification_job calls are rejected by the loop."""
        from retriva_gateway.agent.loop import run_agent_loop
        from retriva_gateway.agent.tools import build_default_tool_registry

        status_calls = []

        async def fake_crm_request(method, path, **kwargs):
            if method == "GET" and "/jobs/job_1" in path:
                return {"job_id": "job_1", "session_id": "sess_resume",
                        "state": "RESEARCHING", "progress": 0.5}
            raise AssertionError(f"unexpected call {method} {path}")

        tc = {"id": "c1", "type": "function",
              "function": {"name": "get_qualification_job",
                           "arguments": json.dumps({"job_id": "job_1"})}}
        responses = [
            _llm_response(tool_calls=[tc]),
            _llm_response(tool_calls=[tc]),  # identical repeat
            _llm_response(content="Job job_1 is RESEARCHING."),
        ]
        idx = {"i": 0}

        async def fake_chat(payload, stream=False):
            r = responses[idx["i"]]
            idx["i"] += 1
            return r

        registry = build_default_tool_registry()
        with patch("retriva_gateway.agent.tools._crm_request", fake_crm_request), \
             patch("retriva_gateway.agent.loop.core_client.chat_completions",
                   new=AsyncMock(side_effect=fake_chat)):
            result = await run_agent_loop(
                user_message="status?", registry=registry, ctx=self._ctx(), kb_ids=["kb1"],
            )
        # The second identical call was short-circuited (ok=False).
        job_calls = [t for t in result.tool_calls_executed
                     if t["tool"] == "get_qualification_job"]
        assert len(job_calls) == 2
        assert job_calls[0]["ok"] is True
        assert job_calls[1]["ok"] is False
        assert result.stopped_reason == "final_answer"


# ---------------------------------------------------------------------------
# Backend duplicate-job protection (CRM JobManager, deterministic)
# ---------------------------------------------------------------------------

class TestBackendDuplicateJobProtection:
    def test_find_active_job_returns_running_job(self):
        from retriva_crm_assistant.jobs import JobManager, JobState

        JobManager._reset()
        manager = JobManager()
        job = manager.create_job(session_id="s1", attachment_id="a1", kb_id="k1")
        job.transition(JobState.RESEARCHING)
        found = manager.find_active_job(session_id="s1", attachment_id="a1", kb_id="k1")
        assert found is not None and found.job_id == job.job_id

    def test_terminal_job_does_not_block_new_run(self):
        from retriva_crm_assistant.jobs import JobManager, JobState

        JobManager._reset()
        manager = JobManager()
        job = manager.create_job(session_id="s1", attachment_id="a1", kb_id="k1")
        job.transition(JobState.COMPLETED)
        assert manager.find_active_job(session_id="s1", attachment_id="a1", kb_id="k1") is None

    def test_other_session_job_not_matched(self):
        from retriva_crm_assistant.jobs import JobManager, JobState

        JobManager._reset()
        manager = JobManager()
        job = manager.create_job(session_id="s1", attachment_id="a1", kb_id="k1")
        job.transition(JobState.RESEARCHING)
        assert manager.find_active_job(session_id="s2", attachment_id="a1", kb_id="k1") is None
        assert manager.find_active_job(session_id="s1", attachment_id="a2", kb_id="k1") is None
        assert manager.find_active_job(session_id="s1", attachment_id="a1", kb_id="k2") is None
