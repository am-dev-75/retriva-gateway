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

"""User-facing forced-routing override (WebUI "company database" switch).

The override changes plane selection only.  The deterministic safety layer
runs first and keeps its terminal outcomes; consequential commands keep the
existing command/confirmation semantics; informational turns enter the agent
loop with the read-only admission subset.
"""

import json

import pytest

from retriva_gateway.agent.loop import _execute_tool
from retriva_gateway.agent.tools import ToolContext, ToolDefinition
from retriva_gateway.api.v2.chat import (
    _AGENT_SENTINEL,
    _AgentAdmission,
    _FORCED_READ_ONLY_AGENT,
    _run_agent_mode,
)
from retriva_gateway.config import settings
from retriva_gateway.core.models import ChatRequest
from retriva_gateway.core.routing.metrics import (
    reset_routing_metrics_for_tests,
    routing_metrics,
)

INCIDENT_IT = (
    "Sto per approvare il batch ibth_9c8c4f121c6e49d6. Ci sono alcune "
    "aziende la cui Disposition è AMBIGUOUS_MATCH. Pe runa di queste, ad "
    "esempio, la reason è \"name-only match on ASEM; human review required "
    "before any canonical write\". Cosa significa? Perché la disposition "
    "non è CREATE_ORGANIZATION come per le altre?"
)
RAG_QUESTION = "What is the return policy in the documentation?"
COMMIT_COMMAND = "Commit the import batch ibth_9c8c4f121c6e49d6"
CLARIFY_COMMAND = "Esegui il commit del batch ibth_9c8c4f121c6e49d6"


def _request(message: str, *, force: bool = True, stream: bool = False
             ) -> ChatRequest:
    return ChatRequest(
        message=message,
        session_id="session-1",
        tools_enabled=False,
        kb_ids=["cust_0007"],
        stream=stream,
        force_deterministic=force,
    )


def test_request_field_is_optional_and_defaults_false():
    assert ChatRequest(message="hello").force_deterministic is False
    assert ChatRequest(
        message="hello", force_deterministic=True
    ).force_deterministic is True


@pytest.mark.parametrize("mode", ["off", "shadow", "active"])
def test_override_forces_read_only_agent_for_plain_question(mode, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
    monkeypatch.setattr(settings, "AGENT_TOOLS_ENABLED", True)
    outcome = _run_agent_mode(_request(RAG_QUESTION), "corr")
    assert outcome is _FORCED_READ_ONLY_AGENT


@pytest.mark.parametrize("mode", ["off", "shadow", "active"])
def test_override_preserves_terminal_safety_clarification(mode, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
    monkeypatch.setattr(settings, "AGENT_TOOLS_ENABLED", True)
    outcome = _run_agent_mode(_request(CLARIFY_COMMAND), "corr")
    # A deterministic guard/veto terminal outcome is returned as the
    # existing clarification, never converted into an agent turn.
    assert outcome is not _FORCED_READ_ONLY_AGENT
    assert outcome is not _AGENT_SENTINEL
    assert not isinstance(outcome, _AgentAdmission)
    body = json.loads(outcome.body)
    assert body["role"] == "assistant"
    assert body["citations"] == []
    assert body["content"]


def test_override_keeps_consequential_command_on_normal_path(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "active")
    monkeypatch.setattr(settings, "AGENT_TOOLS_ENABLED", True)
    outcome = _run_agent_mode(_request(COMMIT_COMMAND), "corr")
    # The write command is NOT downgraded to the read-only subset: it
    # keeps the established agent command/confirmation semantics.
    assert isinstance(outcome, _AgentAdmission)
    assert outcome is not _FORCED_READ_ONLY_AGENT
    assert outcome.claimed is None


def test_flag_absent_keeps_current_behavior(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "off")
    monkeypatch.setattr(settings, "AGENT_TOOLS_ENABLED", True)
    assert _run_agent_mode(_request(RAG_QUESTION, force=False),
                           "corr") is None
    # The incident question is informational in the active pipeline
    # (out of the semantic band) and stays on RAG when the flag is absent.
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "active")
    assert _run_agent_mode(_request(INCIDENT_IT, force=False),
                           "corr") is None


def test_override_emits_content_free_metric(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "active")
    monkeypatch.setattr(settings, "AGENT_TOOLS_ENABLED", True)
    metrics = reset_routing_metrics_for_tests()
    _run_agent_mode(_request(RAG_QUESTION), "corr")
    counters = routing_metrics().snapshot()["counters"]
    forced = [
        c for c in counters
        if c["metric"] == "routing_decision_total"
        and c["labels"].get("source") == "forced_override"
    ]
    assert forced
    assert forced[0]["labels"]["route"] == "AGENT_LOOP"
    # The snapshot never carries the message or any identifier.
    assert RAG_QUESTION not in json.dumps(metrics.snapshot())


def test_override_streaming_falls_through(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "off")
    monkeypatch.setattr(settings, "AGENT_TOOLS_ENABLED", True)
    assert _run_agent_mode(_request(RAG_QUESTION, stream=True),
                           "corr") is None


def test_override_off_mode_never_builds_routing_context(monkeypatch):
    import importlib

    chat_mod = importlib.import_module("retriva_gateway.api.v2.chat")
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "off")
    monkeypatch.setattr(settings, "AGENT_TOOLS_ENABLED", True)

    def explode(*args, **kwargs):
        raise AssertionError("mode off built the workflow-context registry")

    monkeypatch.setattr(chat_mod, "_build_routing_context", explode)
    assert _run_agent_mode(_request(RAG_QUESTION), "corr") is _FORCED_READ_ONLY_AGENT


@pytest.mark.asyncio
async def test_chat_dispatch_uses_read_only_admission(monkeypatch):
    import importlib
    from unittest.mock import AsyncMock

    from fastapi.responses import JSONResponse

    chat_mod = importlib.import_module("retriva_gateway.api.v2.chat")
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "active")
    monkeypatch.setattr(settings, "AGENT_TOOLS_ENABLED", True)
    fake = AsyncMock(return_value=JSONResponse(content={"ok": True}))
    monkeypatch.setattr(chat_mod, "_agent_chat", fake)

    response = await chat_mod.chat(_request(RAG_QUESTION))
    assert response.status_code == 200
    fake.assert_awaited_once()
    assert fake.await_args.kwargs.get("read_only_only") is True


@pytest.mark.asyncio
async def test_chat_dispatch_write_command_is_not_read_only(monkeypatch):
    import importlib
    from unittest.mock import AsyncMock

    from fastapi.responses import JSONResponse

    chat_mod = importlib.import_module("retriva_gateway.api.v2.chat")
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "active")
    monkeypatch.setattr(settings, "AGENT_TOOLS_ENABLED", True)
    fake = AsyncMock(return_value=JSONResponse(content={"ok": True}))
    monkeypatch.setattr(chat_mod, "_agent_chat", fake)

    response = await chat_mod.chat(_request(COMMIT_COMMAND))
    assert response.status_code == 200
    fake.assert_awaited_once()
    assert fake.await_args.kwargs.get("read_only_only") is not True


@pytest.mark.asyncio
async def test_read_only_admission_blocks_destructive_tool():
    calls = []

    async def execute(args, ctx):
        calls.append(args)
        return {"ok": True}

    tool = ToolDefinition(
        name="destructive_probe",
        description="test-only destructive tool",
        parameters={"type": "object", "properties": {},
                    "required": []},
        execute=execute,
        destructive=True,
    )
    ctx = ToolContext(session_id="s", kb_id="default",
                      correlation_id="corr", user_message="commit")
    result = await _execute_tool(
        tool, {"args": {}}, ctx, tool_timeout=1.0, read_only_only=True)
    assert result["error"]["code"] == "tool_not_allowed"
    assert calls == []
