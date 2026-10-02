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

"""Mode gating and legacy compatibility (Spec 001 Phase B, TR84/A61-A68).

Proves the accepted activation model at the chat boundary:
``off`` (default, rollback) keeps the legacy router with EXACT legacy
externally observable behavior — legacy regex routing, legacy streaming
passthrough, and the exact legacy D5 qualification-specific 503 body —
while ``shadow``/``active`` use the deterministic pipeline (generic D5
body; typed clarifications).  Also proves the configuration contract:
strict closed mode values, default off, no per-request overrides.
"""

import json

import pytest
from pydantic import ValidationError

from retriva_gateway.api.v2.chat import (
    _AGENT_SENTINEL,
    _agent_chat,
    _run_agent_mode,
)
from retriva_gateway.core.routing import get_workflow_context_registry
from retriva_gateway.config import Settings, settings
from retriva_gateway.core.models import ChatRequest

# Messages that the LEGACY regex router sends to the agent loop.
LEGACY_WORKFLOW = [
    "Propose a new ACP reference cohort from the active customers",
    "Qualify these candidates",
    "Analyze this import batch",
    "Show me the campaign audience",
    "Yes, enrich the three companies",
    "Review the cohort proposal",
    "Activate ACP version acpver_123",
]
# Messages the legacy router keeps on RAG.
LEGACY_RAG = [
    "What is the return policy in the documentation?",
    "How does the qualification pipeline work?",
    "hello",
]


def _request(message: str, *, stream: bool = False,
             tools_enabled: bool = False, session_id=None) -> ChatRequest:
    return ChatRequest(message=message, session_id=session_id,
                       tools_enabled=tools_enabled,
                       kb_ids=["default"], stream=stream)


# ---------------------------------------------------------------------------
# Configuration contract (TR84 prerequisite).
# ---------------------------------------------------------------------------

def test_default_mode_is_off():
    assert settings.AGENT_INTENT_ROUTER_MODE == "off"


@pytest.mark.parametrize("bad", ["OFF", "Shadow", "bogus", "shadow ", "1"])
def test_invalid_mode_values_fail_startup_validation(bad, monkeypatch):
    monkeypatch.setenv("AGENT_INTENT_ROUTER_MODE", bad)
    with pytest.raises(ValidationError):
        Settings()


def test_mode_is_a_strict_closed_set(monkeypatch):
    for good in ("off", "shadow", "active"):
        monkeypatch.setenv("AGENT_INTENT_ROUTER_MODE", good)
        assert Settings().AGENT_INTENT_ROUTER_MODE == good


# ---------------------------------------------------------------------------
# Mode off: legacy routing preserved exactly (A61-A66, TR84).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", LEGACY_WORKFLOW)
def test_off_mode_routes_legacy_workflow_to_agent(message, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "off")
    assert _run_agent_mode(_request(message), "corr") is _AGENT_SENTINEL


@pytest.mark.parametrize("message", LEGACY_RAG)
def test_off_mode_keeps_plain_rag(message, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "off")
    assert _run_agent_mode(_request(message), "corr") is None


def test_off_mode_preserves_documentation_defect_d2(monkeypatch):
    # The legacy router routes "How do I activate an ACP?" to the agent
    # loop (defect D2).  Mode off preserves it — that is the rollback
    # contract, not a bug to fix here.
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "off")
    assert _run_agent_mode(
        _request("How do I activate an ACP?"), "corr") is _AGENT_SENTINEL


@pytest.mark.parametrize("message", LEGACY_WORKFLOW + LEGACY_RAG)
def test_off_mode_streaming_never_enters_agent_mode(message, monkeypatch):
    # A67a: legacy streaming passthrough in off, for every message.
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "off")
    assert _run_agent_mode(_request(message, stream=True), "corr") is None


def test_explicit_opt_in_still_forces_agent_mode(monkeypatch):
    for mode in ("off", "shadow", "active"):
        monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
        opted_in = _request("hello", tools_enabled=True, session_id="s1")
        assert _run_agent_mode(opted_in, "corr") is _AGENT_SENTINEL
        # Opt-in with stream keeps the legacy warning fallback.
        streaming = _request("hello", tools_enabled=True, session_id="s1",
                             stream=True)
        assert _run_agent_mode(streaming, "corr") is None


def test_master_switch_disables_everything(monkeypatch):
    for mode in ("off", "shadow"):
        monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
        monkeypatch.setattr(settings, "AGENT_TOOLS_ENABLED", False)
        assert _run_agent_mode(
            _request("Propose a new ACP cohort"), "corr") is None


# ---------------------------------------------------------------------------
# D5: the exact legacy 503 body in off; generic in shadow/active.
# ---------------------------------------------------------------------------

LEGACY_D5_BODY = (
    "Candidate qualification cannot be executed from this chat: "
    "{error}. I will not simulate scores or Web Research results."
)


def _agent_chat_503(mode: str, error: str):
    import asyncio
    import retriva_gateway.agent.loop as loop_module
    from unittest.mock import patch

    boom = loop_module.AgentLoopError(error)
    with patch.object(loop_module, "run_agent_loop",
                      side_effect=boom), \
            patch.object(settings, "AGENT_INTENT_ROUTER_MODE", mode):
        return asyncio.run(_agent_chat(
            _request("Qualify these candidates"), "corr-x",
            legacy_error_body=(mode == "off")))


def test_off_mode_preserves_exact_legacy_d5_body(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "off")
    response = _agent_chat_503("off", "crm unavailable")
    assert response.status_code == 503
    body = json.loads(response.body)
    assert body["detail"] == LEGACY_D5_BODY.format(
        error="crm unavailable")


def test_shadow_mode_uses_generic_family_neutral_d5_body(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "shadow")
    response = _agent_chat_503("shadow", "crm unavailable")
    assert response.status_code == 503
    body = json.loads(response.body)
    assert body["detail"] == (
        "The requested workflow cannot be executed from this chat: "
        "crm unavailable. I will not simulate or guess workflow results.")
    assert "Candidate qualification" not in body["detail"]


# ---------------------------------------------------------------------------
# Shadow / active: deterministic pipeline at the chat boundary.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["shadow", "active"])
def test_shadow_active_route_safe_commands_to_agent(mode, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
    for message in ("Propose a new ACP reference cohort from the active "
                    "customers", "Analyze this import batch",
                    "Activate ACP version acpver_123"):
        assert _run_agent_mode(_request(message), "corr") is _AGENT_SENTINEL


@pytest.mark.parametrize("mode", ["shadow", "active"])
def test_shadow_active_keep_informational_on_rag(mode, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
    for message in ("How does ACP activation work?",
                    "What is the return policy?",
                    "hello"):
        assert _run_agent_mode(_request(message), "corr") is None


@pytest.mark.parametrize("mode", ["shadow", "active"])
def test_shadow_active_d2_fix_active(mode, monkeypatch):
    # The D2 fix is visible in shadow/active only.
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
    assert _run_agent_mode(
        _request("How do I activate an ACP?"), "corr") is None


@pytest.mark.parametrize("mode", ["shadow", "active"])
def test_shadow_active_clarifications_are_typed_responses(mode, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
    response = _run_agent_mode(
        _request("Explain the current ACP and activate the newest "
                 "approved version."), "corr")
    assert response is not None and response is not _AGENT_SENTINEL
    body = json.loads(response.body)
    assert body["role"] == "assistant"
    assert body["content"].startswith("This message mentions more")
    assert body["citations"] == []


@pytest.mark.parametrize("mode", ["shadow", "active"])
def test_shadow_active_consequential_without_resource_clarifies(
        mode, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
    response = _run_agent_mode(_request("Approve the ACP"), "corr")
    assert response is not None and response is not _AGENT_SENTINEL
    body = json.loads(response.body)
    assert "exact resource identifier" in body["content"]


@pytest.mark.parametrize("mode", ["shadow", "active"])
def test_shadow_active_bare_yes_falls_to_plain_rag(mode, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
    # Phase C (Spec 001): in shadow/active a bare affirmative is a
    # confirmation-claim candidate — without a valid claim it now
    # CLARIFIES (fail-closed; never a workflow, never RAG-silence that
    # ignores a pending operation).  Mode off keeps the exact legacy
    # plain-RAG behavior (rollback state unchanged).
    result = _run_agent_mode(_request("yes"), "corr")
    if mode == "off":
        assert result is None
    else:
        assert result is not None
        assert result is not _AGENT_SENTINEL
        assert result.status_code == 200
        import json as _json
        body = _json.loads(result.body)
        content = body["content"].lower()
        assert "confirmation" in content or "explicitly" in content
        # No registry state was created by the failed claim.
        assert get_workflow_context_registry().snapshot().pending_total \
            == 0


@pytest.mark.parametrize("mode", ["off", "shadow", "active"])
def test_phase_e_streaming_gate(mode, monkeypatch):
    # Phase E streaming gate (Spec 001 C5/7b): mode off keeps the exact
    # legacy passthrough (no gate); shadow/active use the deterministic
    # engine ONLY — an explicit workflow command over streaming returns
    # the typed 409 refusal, while informational streaming stays the
    # legacy RAG passthrough (None).  The classifier is never invoked.
    import json as _json

    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
    for message in ("Activate ACP version acpver_123",
                    "Propose a new ACP cohort"):
        result = _run_agent_mode(_request(message, stream=True), "corr")
        if mode == "off":
            assert result is None
        else:
            assert result is not None
            assert result.status_code == 409
            body = _json.loads(result.body)
            assert body["detail"]["code"] == "workflow_stream_unsupported"
            assert body["detail"]["retry"]["endpoint"] == "/api/v2/chat"
            assert body["detail"]["retry"]["mode"] == "non_streaming"
    # Informational streaming is never refused (legacy passthrough).
    assert _run_agent_mode(
        _request("How does ACP activation work?", stream=True),
        "corr") is None


def test_active_grants_no_classifier_influence_in_phase_b(monkeypatch):
    # No classifier exists until Phase D: active behaves exactly like
    # shadow at the Phase B boundary (same routes for the same inputs).
    cases = ["Propose a new ACP cohort", "How do I activate an ACP?",
             "Approve the ACP", "Explain ACP and activate acpver_1."]
    for message in cases:
        monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "shadow")
        shadow = _run_agent_mode(_request(message), "corr")
        monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "active")
        active = _run_agent_mode(_request(message), "corr")
        assert type(shadow) is type(active)
        if shadow is None or shadow is _AGENT_SENTINEL:
            assert active is shadow
        else:
            assert json.loads(active.body)["content"] == \
                json.loads(shadow.body)["content"]


def test_rollback_off_restores_legacy_exactly(monkeypatch):
    # TR87 (Phase B portion): switching shadow -> off restores the
    # legacy router decisions for the D1-D5-sensitive messages.
    d_messages = [
        "How do I activate an ACP?",           # D2: agent in legacy
        "Tell me about enriching customers",   # D3 over-match class
        "Approve the ACP",                     # guard clarify in shadow
    ]
    for message in d_messages:
        monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "shadow")
        _run_agent_mode(_request(message), "corr")
        monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "off")
        off_result = _run_agent_mode(_request(message), "corr")
        from retriva_gateway.core.intent import IntentDetector
        assert (off_result is _AGENT_SENTINEL)
        assert IntentDetector.is_crm_workflow(message)
