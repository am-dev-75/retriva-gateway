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

"""Spec 001 Phase D — Gateway classifier interface tests.

Deterministic fakes ONLY (no real provider call, no live endpoint).
Covers: eligibility (the closed ambiguity class); the privacy-safe
request construction; strict re-validation of untrusted C2 output
(including the never-list: no provider/model/endpoint/region fields);
the accepted deterministic policy for shadow (route-neutral) and
active (narrow prerequisites: informational -> RAG, safe workflow ->
agent loop, low confidence -> clarify, consequential -> ALWAYS clarify);
failure degradation (the deterministic result stands); no-recursion
(the adapter never targets chat completions); mode off and streaming
never invoke the classifier; classifier output can never touch Phase C
registry or confirmation state; the request/response schemas carry no
transport-selection fields.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from retriva_gateway.core.routing import (
    ClassifierFailure,
    IntentClassification,
    IntentClassificationError,
    Route,
    WorkflowContextKey,
    WorkflowContextRegistry,
    apply_classification,
    build_classification_request,
    classifier_bypass_reason,
    classifier_config_from_settings,
    classification_context_hints,
    detect_language,
    eligible_for_classification,
    is_consequential_candidate,
    route_non_streaming,
    validate_classification,
)
from retriva_gateway.core.routing.classifier import CoreEndpointClassifier

VALID_C2 = {
    "schema_version": "1",
    "topic": "ACP",
    "intent": "ACP_APPROVAL",
    "mode": "MUTATION",
    "explicitness": "IMPLICIT",
    "confidence": 0.92,
    "requires_clarification": False,
    "language": "en",
    "reason_codes": [],
}


# ---------------------------------------------------------------------------
# Eligibility (A15/A16 and the full never-list)
# ---------------------------------------------------------------------------

ELIGIBLE = ["Handle the import.", "Process the ACP request.",
             "Deal with the campaign members.",
             # Phase E eligibility widening: the non-adjacent ambiguity
             # class (AMBIGUOUS with exactly {NO_DETERMINISTIC_MATCH,
             # NON_ADJACENT_AMBIGUITY}) is eligible alongside the
             # workflow-adjacent CLARIFICATION_REQUIRED class.
             "Yes.", "Review the proposal."]

NEVER = [
    ("Activate acpver_123.", "deterministic command"),
    ("How do I activate acpver_123?", "informational"),
    ("Approve acpver_1 and activate acpver_2.", "multi-intent"),
    ("Approve it.", "Phase C follow-up shape"),
    ("Reject the import batch.", "unavailable vocabulary"),
    ("Do not approve the ACP.", "negated"),
    ("What if we approve the ACP?", "hypothetical"),
    # Gate E correction (E-D1): a recognized consequential operation verb
    # with a missing/generic/unresolved resource is a deterministic
    # consequential candidate — never classifier-eligible.
    ("Commit the batch.", "consequential without resource"),
    ("Roll back the activation.", "consequential without resource"),
    ("Conferma il batch.", "consequential without resource"),
    ("Esegui il rollback dell'attivazione.", "consequential without resource"),
    ("Activate the ACP version.", "consequential without resource"),
    ("Approve the cohort version.", "consequential without resource"),
    ("Supersede the ACP version.", "consequential without resource"),
    ("Accept the enrichment evidence.", "consequential without resource"),
    ("Attiva la versione ACP.", "consequential without resource"),
    ("Approva la versione della coorte.", "consequential without resource"),
]


@pytest.mark.parametrize("message", ELIGIBLE)
def test_eligible_ambiguity(message):
    routed = route_non_streaming(message)
    assert eligible_for_classification(routed) is True


@pytest.mark.parametrize("message,why", NEVER)
def test_never_eligible(message, why):
    routed = route_non_streaming(message)
    assert eligible_for_classification(routed) is False, why


# ---------------------------------------------------------------------------
# Request construction: privacy boundary (§request; §29 minimization)
# ---------------------------------------------------------------------------

def test_request_contains_only_closed_minimal_fields():
    request = build_classification_request(
        "Approve it", max_input_chars=2000,
        ambiguity_class="WORKFLOW_ADJACENT",
        workflow_family_hint="ACP",
        workflow_context_present=True,
        pending_confirmation_present=False,
        correlation_id="corr-1")
    assert set(request) == {
        "schema_version", "prompt_id", "prompt_version", "message",
        "language", "ambiguity_class", "workflow_family_hint",
        "workflow_context_present", "pending_confirmation_present",
        "purpose", "correlation_id"}
    # The never-list: no transport selection, no identity, no
    # confirmation data, no history, no arbitrary metadata.
    for forbidden in ("provider", "model", "base_url", "endpoint",
                      "region", "credentials", "tenant_id",
                      "principal_id", "session_id", "kb_id",
                      "history", "tool_results", "metadata",
                      "preparation_transition_token", "claim_id",
                      "idempotency_key", "resource_id"):
        assert forbidden not in request
    assert request["message"] == "Approve it"
    assert request["purpose"] == "intent-classification"


def test_request_message_truncated_deterministically():
    request = build_classification_request(
        "a" * 5000, max_input_chars=2000,
        ambiguity_class="WORKFLOW_ADJACENT",
        workflow_family_hint=None,
        workflow_context_present=False,
        pending_confirmation_present=False,
        correlation_id="corr-1")
    assert len(request["message"]) == 2000


def test_language_detection_closed():
    assert detect_language("Attiva la versione") == "it"
    assert detect_language("Activate the version") == "en"


def test_context_hints_are_categorical_only():
    registry = WorkflowContextRegistry()
    key = WorkflowContextKey("internal-company", "s", "k")
    hints = classification_context_hints(registry, key)
    assert hints == {"workflow_context_present": False,
                     "pending_confirmation_present": False,
                     "workflow_family_hint": None}
    registry.observe_command(key, "ACP", "acp_version",
                             "acpver_0123456789abcdef", "ACP_REVIEW")
    hints = classification_context_hints(registry, key)
    assert hints["workflow_context_present"] is True
    assert hints["workflow_family_hint"] == "ACP"
    # Only presence booleans + the closed family hint — no resource
    # IDs, no WorkflowContext fields, no confirmation bindings.
    assert "resource_id" not in json.dumps(hints)
    assert "acpver" not in json.dumps(hints)


# ---------------------------------------------------------------------------
# Response re-validation (untrusted advisory output; A20-A22, TR42-44)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mutation", [
    {"confidence": "0.9"},
    {"confidence": None},
    {"confidence": float("nan")},
    {"confidence": float("inf")},
    {"confidence": 1.5},
    {"confidence": -0.1},
    {"schema_version": "2"},
    {"intent": "NOT_AN_INTENT"},
    {"topic": "BOGUS"},
    {"mode": "WEIRD"},
    {"explicitness": "SOMEHOW"},
    {"provider": "openrouter"},        # transport selection rejected
    {"model": "gpt-4"},                # transport selection rejected
    {"tool_arguments": {"x": 1}},       # execution rejected
    {"authorization": True},           # authority rejected
])
def test_invalid_or_forbidden_fields_rejected(mutation):
    with pytest.raises(IntentClassificationError) as exc:
        validate_classification({**VALID_C2, **mutation})
    assert exc.value.category is ClassifierFailure.INVALID_OUTPUT


def test_semantic_contradiction_rejected():
    # ACP intent on a CAMPAIGN topic is contradictory.
    bad = {**VALID_C2, "topic": "CAMPAIGN"}
    with pytest.raises(IntentClassificationError):
        validate_classification(bad)
    # CLARIFICATION_REQUIRED without a reason is contradictory.
    bad = {**VALID_C2, "intent": "CLARIFICATION_REQUIRED",
           "requires_clarification": True, "topic": "GENERAL",
           "mode": "INFORMATIONAL"}
    with pytest.raises(IntentClassificationError):
        validate_classification(bad)


def test_valid_c2_accepted():
    record = validate_classification(dict(VALID_C2))
    assert record.confidence == 0.92


# ---------------------------------------------------------------------------
# Policy: shadow route-neutral; active narrow prerequisites
# ---------------------------------------------------------------------------

def _routed():
    return route_non_streaming("Handle the import.")


def _c2(**overrides):
    return IntentClassification.model_validate(
        {**VALID_C2, **overrides})


def test_shadow_keeps_the_deterministic_route():
    routed = _routed()
    config = classifier_config_from_settings()
    classification = _c2(intent="RAG_QUESTION", topic="GENERAL",
                         mode="INFORMATIONAL", confidence=0.95)
    shadow = apply_classification(
        routed, classification, mode="shadow", config=config)
    assert shadow.route is routed.route  # unchanged
    assert shadow.decision.classifier_invoked is True
    assert shadow.decision.shadow is True
    assert shadow.decision.confidence == 0.95


def test_active_informational_resolves_to_rag():
    routed = _routed()
    config = classifier_config_from_settings()
    classification = _c2(intent="RAG_QUESTION", topic="GENERAL",
                         mode="INFORMATIONAL", confidence=0.95)
    active = apply_classification(
        routed, classification, mode="active", config=config)
    assert active.route is Route.RAG
    assert active.decision.classifier_invoked is True
    assert active.decision.shadow is False


def test_active_below_threshold_clarifies():
    routed = _routed()
    config = classifier_config_from_settings()
    classification = _c2(intent="RAG_QUESTION", topic="GENERAL",
                         mode="INFORMATIONAL", confidence=0.60)
    active = apply_classification(
        routed, classification, mode="active", config=config)
    assert active.route is Route.CLARIFY
    assert active.clarification


def test_active_consequential_always_clarifies():
    routed = _routed()
    config = classifier_config_from_settings()
    for confidence in (0.99, 0.85, 0.70):
        classification = _c2(confidence=confidence)
        active = apply_classification(
            routed, classification, mode="active", config=config)
        assert active.route is Route.CLARIFY, confidence


def test_active_safe_workflow_enters_agent_loop_above_threshold():
    routed = _routed()
    config = classifier_config_from_settings()
    classification = _c2(intent="ACP_COHORT_REVIEW", topic="ACP",
                         mode="ANALYSIS", confidence=0.95)
    active = apply_classification(
        routed, classification, mode="active", config=config)
    assert active.route is Route.AGENT_LOOP


def test_active_safe_workflow_below_safe_threshold_clarifies():
    routed = _routed()
    config = classifier_config_from_settings()
    classification = _c2(intent="ACP_COHORT_REVIEW", topic="ACP",
                         mode="ANALYSIS", confidence=0.88)
    # 0.88 >= min_confidence (0.85) but < safe_workflow (0.90).
    active = apply_classification(
        routed, classification, mode="active", config=config)
    assert active.route is Route.CLARIFY


def test_policy_never_touches_phase_c_state():
    """Classifier output cannot create/modify/claim confirmation
    state or ordinary context (structural + behavioral)."""
    registry = WorkflowContextRegistry()
    key = WorkflowContextKey("internal-company", "s", "k")
    before = registry.snapshot()
    routed = _routed()
    config = classifier_config_from_settings()
    classification = _c2(intent="ACP_ACTIVATION", topic="ACP",
                         mode="DESTRUCTIVE_MUTATION", confidence=0.99)
    active = apply_classification(
        routed, classification, mode="active", config=config)
    assert active.route is Route.CLARIFY  # consequential -> clarify
    assert registry.snapshot() == before
    assert registry.eligible_confirmations(key) == []
    # The result carries no claim and no resolved reference.
    assert active.claimed is None
    assert active.resolved is None


# ---------------------------------------------------------------------------
# The single production adapter (fake transport; no real endpoint)
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.content = json.dumps(payload).encode()

    def json(self):
        return self._payload


class _FakeTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, content=None, headers=None):
        self.calls.append({
            "url": url,
            "payload": json.loads(content),
            "headers": dict(headers or {}),
        })
        return self.response


def _install(monkeypatch, transport):
    def fake_client(timeout=None):
        return transport

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)


def _token(monkeypatch):
    monkeypatch.setattr(
        "retriva_gateway.config.settings"
        ".AGENT_INTENT_CLASSIFIER_SERVICE_AUTH_TOKEN", "svc-token")
    return CoreEndpointClassifier()


def test_adapter_targets_only_the_classification_endpoint(monkeypatch):
    transport = _FakeTransport(_FakeResponse(200, VALID_C2))
    _install(monkeypatch, transport)
    adapter = _token(monkeypatch)
    request = build_classification_request(
        "Handle the import.", max_input_chars=2000,
        ambiguity_class="WORKFLOW_ADJACENT",
        workflow_family_hint=None,
        workflow_context_present=False,
        pending_confirmation_present=False,
        correlation_id="corr-9")
    result = asyncio.run(adapter.classify(request))
    assert result["intent"] == "ACP_APPROVAL"
    call = transport.calls[0]
    # No-recursion: the dedicated endpoint only — NEVER chat
    # completions or any application path.
    assert call["url"].endswith("/v1/intent/classification")
    assert "chat/completions" not in call["url"]
    # The dedicated service credential + accepted purpose marker.
    assert call["headers"]["X-Service-Token"] == "svc-token"
    assert (call["headers"]["X-Retriva-Internal-Purpose"]
            == "intent-classification")
    assert call["headers"]["X-Correlation-ID"] == "corr-9"
    # The request carries no provider/model/endpoint/region fields.
    for forbidden in ("provider", "model", "base_url", "endpoint",
                      "region"):
        assert forbidden not in call["payload"]


def test_adapter_maps_core_errors_to_closed_categories(monkeypatch):
    cases = [
        (504, {"error": {"code": "timeout"}}),
        (500, {"error": {"code": "internal_error"}}),
        (400, {"error": {"code": "invalid_response"}}),
        (503, {"error": {"code": "regional_policy_rejected"}}),
        (503, {"error": {"code": "classifier_disabled"}}),
        (401, {"error": {"code": "unauthenticated"}}),
    ]
    adapter = _token(monkeypatch)
    request = {"correlation_id": "c"}
    for status, payload in cases:
        transport = _FakeTransport(_FakeResponse(status, payload))
        _install(monkeypatch, transport)
        with pytest.raises(IntentClassificationError) as exc:
            asyncio.run(adapter.classify(request))
        assert isinstance(exc.value.category, ClassifierFailure)


def test_adapter_transport_failure_is_unavailable(monkeypatch):
    class _Boom:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            raise httpx.ConnectError("nope")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)
    adapter = _token(monkeypatch)
    with pytest.raises(IntentClassificationError) as exc:
        asyncio.run(adapter.classify({"correlation_id": "c"}))
    assert exc.value.category is ClassifierFailure.CLASSIFIER_UNAVAILABLE


def test_adapter_without_token_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "retriva_gateway.config.settings"
        ".AGENT_INTENT_CLASSIFIER_SERVICE_AUTH_TOKEN", "")
    adapter = CoreEndpointClassifier()
    with pytest.raises(IntentClassificationError) as exc:
        asyncio.run(adapter.classify({"correlation_id": "c"}))
    assert exc.value.category is \
        ClassifierFailure.CLASSIFIER_UNAVAILABLE


# ---------------------------------------------------------------------------
# Mode behavior + streaming: the classifier is never invoked
# ---------------------------------------------------------------------------

def _request(message, *, stream=False, session="s1"):
    from types import SimpleNamespace
    return SimpleNamespace(
        message=message, session_id=session, kb_ids=["default"],
        tools_enabled=False, attachment_ids=[],
        metadata_filters=None, filters=None,
        metadata_filter_mode="soft", stream=stream)


def test_mode_off_never_invokes_the_classifier(monkeypatch):
    from retriva_gateway.api.v2 import chat as chat_module
    from retriva_gateway.config import settings
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "off")
    monkeypatch.setattr(settings, "AGENT_INTENT_CLASSIFIER_ENABLED",
                        True)
    called = {"n": 0}
    original = chat_module._classify_and_apply

    async def spy(*args, **kwargs):
        called["n"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(chat_module, "_classify_and_apply", spy)
    chat_module._run_agent_mode(_request("Handle the import."), "corr")
    assert called["n"] == 0  # off: exact legacy path, no call site use


@pytest.mark.parametrize("mode", ["shadow", "active"])
def test_streaming_never_invokes_the_classifier(mode, monkeypatch):
    from retriva_gateway.api.v2 import chat as chat_module
    from retriva_gateway.config import settings
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
    monkeypatch.setattr(settings, "AGENT_INTENT_CLASSIFIER_ENABLED",
                        True)
    async def spy(*args, **kwargs):
        raise AssertionError("streaming must never classify")

    monkeypatch.setattr(chat_module, "_resolve_classification", spy)
    # The streaming branch uses the deterministic engine (never the
    # classifier) and preserves legacy passthrough for informational
    # streaming; the classifier (_resolve_classification) is never used.
    result = chat_module._run_agent_mode(
        _request("How does ACP activation work?", stream=True), "corr")
    assert result is None


def test_disabled_classifier_never_invoked(monkeypatch):
    from retriva_gateway.api.v2 import chat as chat_module
    from retriva_gateway.config import settings
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "active")
    monkeypatch.setattr(settings, "AGENT_INTENT_CLASSIFIER_ENABLED",
                        False)
    # With the classifier disabled, the eligible ambiguity keeps the
    # ordinary deterministic clarification — no marker, no call.
    result = chat_module._run_agent_mode(
        _request("Handle the import."), "corr")
    assert not isinstance(result, chat_module._ClassifierEligible)
    assert result is not None
    content = json.loads(result.body)["content"]
    assert "import" in content.lower()
    assert "?" in content


@pytest.mark.parametrize("mode", ["shadow", "active"])
def test_classification_failure_degrades_deterministically(
        mode, monkeypatch):
    """TR79/TR75: a failing classifier reproduces the deterministic
    behavior exactly — the deterministic clarification stands."""
    from retriva_gateway.api.v2 import chat as chat_module
    from retriva_gateway.config import settings
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
    monkeypatch.setattr(settings, "AGENT_INTENT_CLASSIFIER_ENABLED",
                        True)
    marker = chat_module._run_agent_mode(
        _request("Handle the import."), "corr")
    assert isinstance(marker, chat_module._ClassifierEligible)

    async def failing(*args, **kwargs):
        raise IntentClassificationError(
            ClassifierFailure.CLASSIFIER_UNAVAILABLE)

    monkeypatch.setattr(
        "retriva_gateway.core.routing.classifier.CoreEndpointClassifier"
        ".classify",
        failing)
    result = asyncio.run(
        chat_module._resolve_classification(marker, "corr"))
    assert result is not None
    assert result.status_code == 200
    content = json.loads(result.body)["content"]
    # The deterministic clarification stands, unchanged.
    assert "import" in content.lower()
    assert "?" in content
    # No other model was invoked (no implicit fallback — the failure
    # path returns the deterministic result only).


# ---------------------------------------------------------------------------
# Gate E correction (E-D1): a recognized consequential operation verb with a
# missing/generic/unresolved resource is a deterministic consequential
# candidate — never classifier-eligible, never a classifier call, never an
# agent-loop admission, never a tool.  EN + IT required examples.
# ---------------------------------------------------------------------------

GATE_E_CONSEQUENTIAL = [
    # EN
    "Commit the batch.",
    "Roll back the activation.",
    "Activate the ACP version.",
    "Approve the cohort version.",
    "Supersede the ACP version.",
    "Accept the enrichment evidence.",
    # IT
    "Conferma il batch.",
    "Esegui il rollback dell'attivazione.",
    "Attiva la versione ACP.",
    "Approva la versione della coorte.",
]


@pytest.mark.parametrize("message", GATE_E_CONSEQUENTIAL)
def test_gate_e_consequential_never_eligible(message):
    routed = route_non_streaming(message)
    # Deterministic consequential candidate -> clarification, never RAG and
    # never the agent loop; the classifier is structurally excluded.
    assert routed.route is Route.CLARIFY
    assert routed.decision.classifier_invoked is False
    assert is_consequential_candidate(routed) is True
    assert eligible_for_classification(routed) is False
    # The closed bypass reason is emitted, not a classifier call.
    assert classifier_bypass_reason(routed) == "consequential_candidate"


@pytest.mark.parametrize("message", GATE_E_CONSEQUENTIAL)
def test_gate_e_consequential_never_invokes_classifier(message, monkeypatch):
    from retriva_gateway.api.v2 import chat as chat_module
    from retriva_gateway.config import settings
    monkeypatch.setattr(settings, "AGENT_TOOLS_ENABLED", True)
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "active")
    monkeypatch.setattr(settings, "AGENT_INTENT_CLASSIFIER_ENABLED", True)
    # Spy on the SINGLE classifier call site: it must not be reached.
    called = {"n": 0}
    original = chat_module._resolve_classification

    async def _spy(*args, **kwargs):
        called["n"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(chat_module, "_resolve_classification", _spy)
    result = chat_module._run_agent_mode(_request(message), "corr")
    assert called["n"] == 0
    # Deterministically clarified, never an agent-loop admission.
    assert result is not chat_module._AGENT_SENTINEL
    from fastapi.responses import JSONResponse
    assert isinstance(result, JSONResponse)
    assert result.status_code == 200


@pytest.mark.parametrize("message", GATE_E_CONSEQUENTIAL)
def test_gate_e_consequential_classifier_downcall_not_reached(
        message, monkeypatch):
    from retriva_gateway.api.v2 import chat as chat_module
    from retriva_gateway.config import settings
    monkeypatch.setattr(settings, "AGENT_TOOLS_ENABLED", True)
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "active")
    monkeypatch.setattr(settings, "AGENT_INTENT_CLASSIFIER_ENABLED", True)
    # If the classifier downcall were ever reached it would raise — so a
    # clean route proves it is never attempted.
    monkeypatch.setattr(
        "retriva_gateway.core.routing.classifier.CoreEndpointClassifier"
        ".classify",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("classifier must not be called")))
    result = chat_module._run_agent_mode(_request(message), "corr")
    from fastapi.responses import JSONResponse
    assert isinstance(result, JSONResponse)
    assert result.status_code == 200


def test_gate_e_valid_resource_consequential_enters_agent_loop():
    # A consequential verb WITH an explicit opaque resource stays
    # deterministic and classifier-free (Gate E: explicit valid resource ->
    # agent loop), never classifier-eligible.
    for message in ("Commit batch batch_123.", "Attiva acpver_123.",
                    "Approva acpver_9 dell'ACP."):
        routed = route_non_streaming(message)
        assert routed.route is Route.AGENT_LOOP
        assert routed.decision.classifier_invoked is False
        assert eligible_for_classification(routed) is False


def test_gate_e_safe_unresolved_workflow_remains_eligible():
    # Gate E narrows only consequential-verb ambiguity; a safe unresolved
    # workflow reference stays classifier-eligible (never a consequential
    # candidate).
    for message in ("Review the proposal.", "Handle the import."):
        routed = route_non_streaming(message)
        assert is_consequential_candidate(routed) is False
        assert eligible_for_classification(routed) is True
