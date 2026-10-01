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

"""Gate B correction proofs (Spec 001 / ADR-0002, owner decisions D-1..D-3).

TR88-TR94 (acceptance.md, "Gate B correction requirements"): the D-1
negation scope over safe workflow verbs, the D-2 informational and
multi-intent corners (D-2a multi-intent identification without family
nouns; D-2c interrogative frames with operation verbs and opaque
identifiers stay informational while imperative counterparts route to
the workflow), and the D-3 C1 extension for the accepted ACP
evidence-enrichment vocabulary (per the accepted agent/tools.py
ToolDefinitions and ADR-024).  Plus the proofs that the correction does
not weaken the Phase B invariants: repeatability, mode gating (off =
legacy router decisions; shadow == active), no classifier invocation,
and classification with sockets disabled.
"""

import json
import socket

import pytest

from retriva_gateway.core.routing import (
    CONSEQUENTIAL_INTENTS,
    DeterministicEngine,
    evaluate_consequential_guard,
    route_non_streaming,
)
from retriva_gateway.core.routing.taxonomy import (
    Explicitness,
    Intent,
    InteractionMode,
    ReasonCode,
    Route,
)

ENGINE = DeterministicEngine()


def route_of(message: str) -> Route:
    return route_non_streaming(message).route


# ---------------------------------------------------------------------------
# TR88 — D-1: negated safe-workflow verbs never enter the agent loop (EN/IT).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "Do not propose a cohort.",
    "Do not analyze this import.",
    "Non creare una proposta di coorte.",
    "Non analizzare questa importazione.",
])
def test_tr88_negated_safe_verbs_never_enter_the_workflow(message):
    result = ENGINE.classify(message)
    assert result.rule == "R-NEGATION"
    assert result.explicitness is Explicitness.NEGATED
    assert result.consequential_operations == ()
    routed = route_non_streaming(message)
    assert routed.route is Route.RAG
    assert routed.decision.intent is Intent.RAG_QUESTION
    assert routed.decision.classifier_invoked is False


# ---------------------------------------------------------------------------
# TR89 — D-2a: informational + consequential multi-intent clarifies.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "How does activation work? Activate acpver_123.",
    "Come funziona l'attivazione? Attiva acpver_123.",
])
def test_tr89_informational_plus_consequential_clarifies(message):
    # The informational clause carries no family noun: the consequential
    # clause's recognized operation and opaque identifier identify the
    # family (D-2a), and the analysis considers the complete message
    # before any informational rule can terminate evaluation.
    result = ENGINE.classify(message)
    assert result.rule == "R-MULTI-INTENT"
    assert result.intent is Intent.CLARIFICATION_REQUIRED
    assert "ACP:ACP_ACTIVATION" in result.consequential_operations
    routed = route_non_streaming(message)
    # Clarification, never partial execution, never a RAG answer that
    # silently ignores the consequential command.
    assert routed.route is Route.CLARIFY
    assert ReasonCode.MULTI_INTENT in routed.decision.reason_codes
    assert "more than one action" in routed.clarification
    assert "separate message" in routed.clarification
    assert routed.decision.classifier_invoked is False


# ---------------------------------------------------------------------------
# TR90 — D-2c: interrogative frames with operation verbs and opaque
# identifiers stay informational.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "How do I activate acpver_123?",
    "Come si attiva acpver_123?",
    "How do I approve acpver_1?",
    "How do I commit batch_7?",
    "How do I supersede acpver_2?",
])
def test_tr90_interrogative_frames_with_identifiers_stay_informational(
        message):
    result = ENGINE.classify(message)
    assert result.rule == "R-DOC-FRAMING"
    assert result.mode is InteractionMode.INFORMATIONAL
    assert result.consequential_operations == ()
    assert route_of(message) is Route.RAG


# ---------------------------------------------------------------------------
# TR91 — D-2c counterpart: imperative forms with the same operation and
# identifiers route to the workflow through the consequential guard.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "Activate acpver_123.",
    "Attiva acpver_123.",
    "Approve acpver_1.",
    "Commit batch_7.",
])
def test_tr91_imperative_forms_enter_the_workflow_through_the_guard(
        message):
    result = ENGINE.classify(message)
    assert result.rule == "R-COMMAND"
    assert result.explicitness is Explicitness.EXPLICIT
    assert result.intent in CONSEQUENTIAL_INTENTS
    assert result.consequential_operations == (f"{result.topic.value}:"
                                               f"{result.intent.value}",)
    assert evaluate_consequential_guard(result).passed is True
    assert route_of(message) is Route.AGENT_LOOP


# ---------------------------------------------------------------------------
# TR92 — D-3: the enrichment request routes per its accepted
# consequential semantics (destructive=True, explicit-approval-only).
# ---------------------------------------------------------------------------

def test_tr92_enrichment_request_with_resource_enters_agent_loop():
    result = ENGINE.classify("Enrich cohort version cohver_9")
    assert result.rule == "R-COMMAND"
    assert result.intent is Intent.ACP_EVIDENCE_ENRICHMENT
    assert result.explicitness is Explicitness.EXPLICIT
    assert result.resource_reference == "cohver_9"
    assert result.consequential_operations == ("ACP:ACP_EVIDENCE_ENRICHMENT",)
    # D-3 per the accepted ToolDefinitions (destructive=True) and ADR-024.
    assert result.mode is InteractionMode.DESTRUCTIVE_MUTATION
    assert evaluate_consequential_guard(result).passed is True
    assert route_of("Enrich cohort version cohver_9") is Route.AGENT_LOOP


def test_tr92_enrichment_request_without_resource_fails_closed():
    routed = route_non_streaming("Enrich the customers")
    assert routed.route is Route.CLARIFY
    assert ReasonCode.GUARD_RESOURCE_UNRESOLVED in routed.decision.reason_codes
    assert routed.decision.source.value == "guard"
    # The closed consequential-resource template names the operation.
    assert "start the evidence enrichment" in routed.clarification


# ---------------------------------------------------------------------------
# TR93 — D-3: enrichment-job status/result queries are safe reads.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "Show me the enrichment job ench_5",
    "Check the enrichment job ench_5",
])
def test_tr93_enrichment_job_queries_route_as_safe_reads(message):
    result = ENGINE.classify(message)
    assert result.rule == "R-COMMAND"
    assert result.intent is Intent.ACP_EVIDENCE_ENRICHMENT_STATUS
    assert result.consequential_operations == ()
    assert result.mode is InteractionMode.ANALYSIS
    assert result.resource_reference == "ench_5"
    assert evaluate_consequential_guard(result).passed is True
    assert route_of(message) is Route.AGENT_LOOP


# ---------------------------------------------------------------------------
# TR94 — D-3: evidence acceptance is consequential (destructive=True,
# audited, supersedes per field): guarded entry, fail-closed without a
# resource, and negation never executes.
# ---------------------------------------------------------------------------

def test_tr94_acceptance_with_resource_enters_agent_loop():
    message = "Accept the enrichment evidence from job ench_5"
    result = ENGINE.classify(message)
    assert result.rule == "R-COMMAND"
    assert result.intent is Intent.ACP_EVIDENCE_ACCEPTANCE
    assert result.resource_reference == "ench_5"
    assert result.consequential_operations == ("ACP:ACP_EVIDENCE_ACCEPTANCE",)
    assert result.mode is InteractionMode.DESTRUCTIVE_MUTATION
    assert evaluate_consequential_guard(result).passed is True
    assert route_of(message) is Route.AGENT_LOOP


def test_tr94_acceptance_without_resource_fails_closed():
    routed = route_non_streaming("Accept the enrichment results")
    assert routed.route is Route.CLARIFY
    assert ReasonCode.GUARD_RESOURCE_UNRESOLVED in routed.decision.reason_codes
    assert routed.decision.source.value == "guard"


def test_tr94_negated_acceptance_falls_to_rag():
    routed = route_non_streaming("Do not accept the enrichment evidence")
    assert routed.route is Route.RAG
    assert routed.decision.intent is Intent.RAG_QUESTION
    assert routed.decision.explicitness is Explicitness.NEGATED


# ---------------------------------------------------------------------------
# D-2c veto mechanics: the R-DOC-FRAMING command veto requires a
# closed-set imperative marker in the same clause.
# ---------------------------------------------------------------------------

def test_d2c_veto_requires_an_imperative_marker():
    # Without a marker the interrogative frame stays informational (TR90).
    assert ENGINE.classify(
        "How do I activate acpver_123?").rule == "R-DOC-FRAMING"
    # With a marker, a verb, and an identifier in the same doc-framed
    # clause the veto abstains from doc-framing — and the message still
    # never routes to a workflow from an informational rule: it falls
    # through to the fail-closed ambiguous default (never AGENT_LOOP).
    message = "How do I activate acpver_123 please activate acpver_123"
    result = ENGINE.classify(message)
    assert result.rule != "R-DOC-FRAMING"
    assert route_of(message) is Route.RAG


def test_d2c_plain_imperatives_with_markers_are_commands():
    # Markers outside doc-framed clauses are ordinary imperative forms.
    result = ENGINE.classify("Please activate acpver_123.")
    assert result.rule == "R-COMMAND"
    assert result.intent is Intent.ACP_ACTIVATION
    assert route_of("Please activate acpver_123.") is Route.AGENT_LOOP


# ---------------------------------------------------------------------------
# Correction-wide invariants.
# ---------------------------------------------------------------------------

CORRECTION_CASES = [
    "Do not propose a cohort.",
    "Do not analyze this import.",
    "Non creare una proposta di coorte.",
    "Non analizzare questa importazione.",
    "How does activation work? Activate acpver_123.",
    "Come funziona l'attivazione? Attiva acpver_123.",
    "How do I activate acpver_123?",
    "Come si attiva acpver_123?",
    "How do I approve acpver_1?",
    "How do I commit batch_7?",
    "How do I supersede acpver_2?",
    "Activate acpver_123.",
    "Attiva acpver_123.",
    "Approve acpver_1.",
    "Commit batch_7.",
    "Enrich cohort version cohver_9",
    "Enrich the customers",
    "Show me the enrichment job ench_5",
    "Check the enrichment job ench_5",
    "Accept the enrichment evidence from job ench_5",
    "Accept the enrichment results",
    "Do not accept the enrichment evidence",
]


def test_correction_routes_never_invoke_a_classifier():
    import retriva_gateway.core.routing as routing_pkg
    assert not hasattr(routing_pkg, "classifier")
    for message in CORRECTION_CASES:
        routed = route_non_streaming(message)
        assert routed.decision.classifier_invoked is False
        assert routed.decision.source.value in {"deterministic", "guard"}


def test_correction_outcomes_are_repeatable():
    for message in CORRECTION_CASES:
        first = route_non_streaming(message)
        for _ in range(4):
            assert route_non_streaming(message) == first


def test_correction_classification_works_with_sockets_disabled():
    class _NoSockets:
        def __enter__(self):
            self._orig = socket.socket
            socket.socket = self._raise
            return self

        def __exit__(self, *exc):
            socket.socket = self._orig
            return False

        @staticmethod
        def _raise(*args, **kwargs):
            raise AssertionError("network access attempted")

    expected = {
        "Do not propose a cohort.": Route.RAG,
        "How does activation work? Activate acpver_123.": Route.CLARIFY,
        "How do I activate acpver_123?": Route.RAG,
        "Activate acpver_123.": Route.AGENT_LOOP,
        "Enrich cohort version cohver_9": Route.AGENT_LOOP,
        "Show me the enrichment job ench_5": Route.AGENT_LOOP,
        "Accept the enrichment evidence from job ench_5": Route.AGENT_LOOP,
        "Accept the enrichment results": Route.CLARIFY,
    }
    with _NoSockets():
        for message, route in expected.items():
            assert route_of(message) is route


# ---------------------------------------------------------------------------
# Mode gating: off keeps the legacy router; shadow == active (Phase B has
# no classifier, so the correction pipeline is mode-invariant).
# ---------------------------------------------------------------------------

def _request(message: str):
    from retriva_gateway.core.models import ChatRequest
    return ChatRequest(message=message, session_id="corr-1",
                       tools_enabled=False, kb_ids=["default"])


def test_off_mode_keeps_legacy_router_decisions(monkeypatch):
    from retriva_gateway.api.v2.chat import _AGENT_SENTINEL, _run_agent_mode
    from retriva_gateway.config import settings
    from retriva_gateway.core.intent import IntentDetector
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "off")
    for message in ("Activate ACP version acpver_123",
                    "How do I activate an ACP?",
                    "Do not propose a cohort.",
                    "Enrich the customers"):
        off = _run_agent_mode(_request(message), "corr")
        assert (off is _AGENT_SENTINEL) == \
            IntentDetector.is_crm_workflow(message)


def test_shadow_equals_active_for_correction_messages(monkeypatch):
    from retriva_gateway.api.v2.chat import _AGENT_SENTINEL, _run_agent_mode
    from retriva_gateway.config import settings
    for message in ("Do not propose a cohort.",
                    "How does activation work? Activate acpver_123.",
                    "How do I activate acpver_123?",
                    "Enrich the customers",
                    "Accept the enrichment evidence from job ench_5"):
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
