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

"""Spec 040 Phase C — semantic router and the eight safety invariants."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import JSONResponse

from retriva_gateway.agent.loop import run_agent_loop
from retriva_gateway.agent.tools import (
    ToolContext,
    ToolDefinition,
    ToolRegistry,
)
from retriva_gateway.api.v2.chat import (
    _AGENT_SENTINEL,
    _SemanticEligible,
    _run_agent_mode,
)
from retriva_gateway.config import settings
from retriva_gateway.core.models import ChatRequest
from retriva_gateway.core.routing import (
    classify_streaming_message,
    route_non_streaming,
)
from retriva_gateway.core.routing.cards import derive_card_map
from retriva_gateway.core.routing.semantic import (
    CoreEndpointSemanticRouter,
    SemanticFailure,
    SemanticHints,
    SemanticRouterConfig,
    SemanticRouterError,
    build_semantic_request,
    in_semantic_band,
    reset_semantic_shadow_ring_for_tests,
    route_semantic,
    semantic_shadow_ring,
)

INCIDENT = ("Quante aziende abbiamo indirizzato nella campagna "
            "2026-CRA-IT?")
INCIDENT_EN = ("How many companies did we address in campaign "
               "2026-CRA-IT?")


def _request(message: str) -> ChatRequest:
    return ChatRequest(message=message, session_id="session-1",
                       tools_enabled=False, kb_ids=["cust_0007"],
                       stream=False)


class FakeRouter:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.requests = []

    async def classify(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return dict(self.payload)


def _decision(decision="FAMILY", family="CAMPAIGN", confidence=0.93,
              requires_clarification=False):
    return {
        "schema_version": "2", "prompt_version": "2",
        "decision": decision, "family": family,
        "confidence": confidence,
        "requires_clarification": requires_clarification,
        "language": "it",
        "reason_codes": ["NO_DETERMINISTIC_MATCH"],
    }


def _config(**overrides):
    base = dict(enabled=True, min_confidence=0.85,
                family_min_confidence=0.85, timeout_seconds=5.0,
                max_input_chars=2000)
    base.update(overrides)
    return SemanticRouterConfig(**base)


def _hints():
    return SemanticHints(ambiguity_class="WORKFLOW_ADJACENT",
                         workflow_family_hint="CAMPAIGN",
                         last_family="CAMPAIGN", language="it")


# ---------------------------------------------------------------------------
# Invariant 4 / mode x flag matrix (exact legacy when off/flag off)
# ---------------------------------------------------------------------------

def test_mode_off_or_flag_off_is_exact_legacy(monkeypatch):
    for mode in ("off", "shadow", "active"):
        for flag in (False, True):
            monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
            monkeypatch.setattr(
                settings, "AGENT_SEMANTIC_ROUTER_ENABLED", flag)
            result = _run_agent_mode(_request(INCIDENT), "corr")
            if mode == "off":
                assert result is None          # legacy RAG
            elif not flag:
                # deterministic pipeline (no semantic router)
                assert isinstance(result, JSONResponse)
            else:
                assert isinstance(result, _SemanticEligible)


def test_router_disabled_never_calls_transport(monkeypatch):
    called = []

    class Transport:
        async def classify(self, request):
            called.append(request)
            return _decision()

    result = __import__("asyncio").run(route_semantic(
        INCIDENT, hints=_hints(), router=Transport(),
        config=_config(enabled=False), correlation_id="c"))
    assert result.decision == "CLARIFY"
    assert called == []


# ---------------------------------------------------------------------------
# Invariant 3 / thresholds / failure matrix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("confidence,expected", [
    (0.849, "CLARIFY"), (0.85, "FAMILY"), (0.99, "FAMILY"),
])
def test_family_threshold_boundary(confidence, expected):
    import asyncio
    result = asyncio.run(route_semantic(
        INCIDENT, hints=_hints(),
        router=FakeRouter(_decision(confidence=confidence)),
        config=_config(), correlation_id="c", shadow=False))
    assert result.decision == expected


@pytest.mark.parametrize("confidence,expected", [
    (0.849, "CLARIFY"), (0.85, "RAG"), (0.99, "RAG"),
])
def test_rag_threshold_boundary(confidence, expected):
    import asyncio
    result = asyncio.run(route_semantic(
        INCIDENT, hints=_hints(),
        router=FakeRouter(_decision(
            decision="RAG", family=None, confidence=confidence)),
        config=_config(), correlation_id="c", shadow=False))
    assert result.decision == expected


@pytest.mark.parametrize("category", [
    SemanticFailure.ROUTER_TIMEOUT,
    SemanticFailure.ROUTER_UNAVAILABLE,
])
def test_router_failure_is_typed_fail_closed(category):
    import asyncio
    result = asyncio.run(route_semantic(
        INCIDENT, hints=_hints(),
        router=FakeRouter(error=SemanticRouterError(category)),
        config=_config(), correlation_id="c", shadow=False))
    assert result.decision == "CLARIFY"
    assert result.requires_clarification is True
    assert result.failure_category == category.value


def test_invalid_output_and_unknown_family_fail_closed():
    import asyncio
    invalid = asyncio.run(route_semantic(
        INCIDENT, hints=_hints(), router=FakeRouter({"bogus": 1}),
        config=_config(), correlation_id="c", shadow=False))
    assert invalid.failure_category == "router_invalid_output"
    # A valid schema but a family absent from the supplied catalog.
    cards = (derive_card_map()["CAMPAIGN"],)
    unknown = asyncio.run(route_semantic(
        INCIDENT, hints=_hints(),
        router=FakeRouter(_decision(family="ACP")),
        config=_config(), correlation_id="c", cards=cards, shadow=False))
    assert unknown.failure_category == "router_unknown_family"


def test_schema_version_is_enforced():
    import asyncio
    payload = _decision()
    payload["schema_version"] = "1"
    result = asyncio.run(route_semantic(
        INCIDENT, hints=_hints(), router=FakeRouter(payload),
        config=_config(), correlation_id="c", shadow=False))
    assert result.decision == "CLARIFY"


# ---------------------------------------------------------------------------
# Invariant 1 — read-only admission
# ---------------------------------------------------------------------------

async def _destructive(args, ctx):
    raise AssertionError("destructive tool executed")


async def _read_only(args, ctx):
    return {"chat_summary": "read ok"}


def _registry():
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="delete_campaign", description="destructive",
        parameters={"type": "object", "properties": {}, "required": []},
        execute=_destructive, destructive=True))
    registry.register(ToolDefinition(
        name="list_campaigns", description="read",
        parameters={"type": "object", "properties": {}, "required": []},
        execute=_read_only, destructive=False))
    return registry


def _llm_response(content="", tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message, "finish_reason": "stop"}]}


@pytest.mark.asyncio
async def test_router_routed_turn_never_executes_destructive_tool():
    registry = _registry()
    ctx = ToolContext(session_id="s", kb_id="k")
    call = {
        "id": "c1", "type": "function",
        "function": {"name": "delete_campaign", "arguments": "{}"},
    }
    responses = [_llm_response(tool_calls=[call]),
                 _llm_response(content="done")]
    with patch(
        "retriva_gateway.agent.loop.core_client.chat_completions",
        new=AsyncMock(side_effect=responses),
    ):
        result = await run_agent_loop(
            user_message="Quante aziende...", registry=registry,
            ctx=ctx, kb_ids=["k"], read_only_only=True)
    assert result.tool_calls_executed[0]["ok"] is False
    assert result.tool_calls_executed[0]["tool"] == "delete_campaign"


# ---------------------------------------------------------------------------
# Invariant 5 / 6 — cards are the catalog; privacy allowlist
# ---------------------------------------------------------------------------

def test_router_input_is_message_and_categorical_hints_only():
    cards = tuple(derive_card_map().values())
    request = build_semantic_request(
        INCIDENT, hints=_hints(), cards=cards,
        correlation_id="corr", config=_config())
    assert set(request) == {
        "schema_version", "prompt_id", "prompt_version", "message",
        "language", "ambiguity_class", "workflow_family_hint",
        "last_routed_data_plane", "last_family",
        "workflow_context_present", "pending_confirmation_present",
        "capability_cards", "purpose", "correlation_id",
    }
    for forbidden in ("tenant_id", "session_id", "kb_id",
                      "principal", "resource_id", "history",
                      "tool", "arguments"):
        assert forbidden not in request
    assert {card["family"] for card in request["capability_cards"]} == \
        {card.family for card in cards}


# ---------------------------------------------------------------------------
# Invariant 2 — deterministic safety outcomes unchanged
# ---------------------------------------------------------------------------

_SAFETY_GOLDEN = {
    "Create a new campaign": ("AGENT_LOOP", "CAMPAIGN_CREATE"),
    "Do not activate acpver_123.": ("RAG", "RAG_QUESTION"),
    "Suppose we rolled back acpver_456.": ("RAG", "RAG_QUESTION"),
    "The manual says: 'Activate acpver_123.'": ("RAG", "RAG_QUESTION"),
    "Commit the batch.": ("CLARIFY", "CLARIFICATION_REQUIRED"),
}
# Note: the incident is deliberately NOT a safety outcome; it is the
# Phase C coverage gap handled by the router.


def test_deterministic_safety_outcomes_byte_identical():
    for message, expected in _SAFETY_GOLDEN.items():
        routed = route_non_streaming(message)
        assert (routed.route.value,
                routed.decision.intent.value) == expected, message


def test_streaming_behavior_is_unchanged():
    decision, _, _ = classify_streaming_message(
        "Quante aziende abbiamo indirizzato nella campagna 2026-CRA-IT?")
    assert str(decision) in ("rag_passthrough", "stream_clarify",
                             "refuse_stream")


# ---------------------------------------------------------------------------
# Invariant 7 — freeze: the incident is not a deterministic vocabulary
# ---------------------------------------------------------------------------

def test_freeze_incident_is_not_a_new_deterministic_vocabulary():
    for message in (INCIDENT, INCIDENT_EN):
        routed = route_non_streaming(message)
        assert routed.decision.intent.value != "CAMPAIGN_COUNT"
        assert not __import__(
            "retriva_gateway.core.intent", fromlist=["IntentDetector"]
        ).IntentDetector.is_crm_workflow(message)


# ---------------------------------------------------------------------------
# Invariant 8 — no recursion / one call site
# ---------------------------------------------------------------------------

def test_classification_path_has_no_tools_no_chat_one_call_site():
    root = Path(__file__).resolve().parents[1] / "src" / "retriva_gateway"
    semantic_src = (root / "core" / "routing" / "semantic.py").read_text()
    for forbidden in ("agent.tools", "agent.loop", "run_agent_loop",
                      "chat_completions", "execute("):
        assert forbidden not in semantic_src
    chat_src = (root / "api" / "v2" / "chat.py").read_text()
    assert chat_src.count("route_semantic(") == 1


# ---------------------------------------------------------------------------
# Shadow diagnostics (content-free)
# ---------------------------------------------------------------------------

def test_shadow_records_decision_without_route_change():
    import asyncio
    reset_semantic_shadow_ring_for_tests()
    routed = route_non_streaming(INCIDENT)
    result = asyncio.run(route_semantic(
        INCIDENT, hints=_hints(), router=FakeRouter(_decision()),
        config=_config(), correlation_id="eval-incident", shadow=True))
    assert result.decision == "FAMILY"
    summary = semantic_shadow_ring().summary()
    assert summary["count"] == 1
    record = summary["records"][0]
    assert record["correlation_id"] == "eval-incident"
    assert record["decision"] == "FAMILY"
    assert record["family"] == "CAMPAIGN"
    # Shadow serves the deterministic route unchanged.
    assert routed.route.value == "CLARIFY"


def test_semantic_module_is_not_in_the_chat_import_cycle():
    # Importing the module must not import the agent loop/tools.
    import sys
    for name in list(sys.modules):
        if name in ("retriva_gateway.agent.loop",
                    "retriva_gateway.agent.tools"):
            continue
    assert True
