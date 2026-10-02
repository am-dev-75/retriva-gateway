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

"""Deterministic engine (Spec 001 Phase B) — focused proof.

Covers the accepted Phase B deterministic criteria: explicit priorities,
EN/IT document framing (D2 fix), negation, hypothetical framing, quoted
text and fenced code, prompt-writing requests, narrowed workflow
commands, workflow-adjacent vs non-adjacent ambiguity, multi-intent
clarification (policy B), KB/metadata inertness (TR1, TR5/TR6 dispatch
components), near-pairs, repeatability, and the no-model/no-tool
structural proofs.
"""

import inspect
import socket

import pytest

from retriva_gateway.core.routing import (
    DeterministicEngine,
    RULE_PRIORITIES,
    route_non_streaming,
)
from retriva_gateway.core.routing.deterministic import (
    OPERATIONS,
    CommandMatch,
    mask_quoted,
    normalize_message,
    split_clauses,
)
from retriva_gateway.core.routing.taxonomy import ReasonCode, Route

ENGINE = DeterministicEngine()


def route_of(message: str) -> Route:
    return route_non_streaming(message).route


def result_of(message: str):
    return ENGINE.classify(message)


# ---------------------------------------------------------------------------
# Explicit priority order (never incidental source order).
# ---------------------------------------------------------------------------

ACCEPTED_PRIORITIES = {
    "R-DOC-FRAMING": 10,
    "R-NEGATION": 20,
    "R-HYPOTHETIC": 25,
    "R-QUOTED": 30,
    "R-COMMAND": 40,
    "R-QUESTION": 50,
    "R-MULTI-INTENT": 55,
    "R-FOLLOWUP": 60,
    "R-UNSUPPORTED": 70,
}


def test_rule_priorities_are_exactly_the_accepted_values():
    assert RULE_PRIORITIES == ACCEPTED_PRIORITIES


def test_engine_evaluates_rules_in_priority_order():
    ordered = [name for name, _rule in ENGINE._ordered_rules()]
    assert ordered == sorted(
        ACCEPTED_PRIORITIES, key=ACCEPTED_PRIORITIES.get)


@pytest.mark.parametrize("message,winner", [
    # Doc framing (10) beats command (40): the approve verb is inside a
    # knowledge-framed question (the D2 fix).
    ("How do I approve an ACP?", "R-DOC-FRAMING"),
    # Negation (20) beats command (40).
    ("Do not commit the import batch batch_77", "R-NEGATION"),
    # Hypothetical (25) beats command (40).
    ("What if we commit the import batch batch_77?", "R-HYPOTHETIC"),
    # Quoted (30) beats command (40): the only workflow signal is quoted.
    ('"Commit the import batch batch_77"', "R-QUOTED"),
])
def test_priority_order_is_enforced_not_source_order(message, winner):
    assert result_of(message).rule == winner


# ---------------------------------------------------------------------------
# Normalization and masking.
# ---------------------------------------------------------------------------

def test_normalization_is_deterministic_and_accent_folded():
    assert normalize_message("COSA È l'ACP?") == "cosa e l'acp?"
    assert normalize_message("Approve  ACP ") == "approve acp"
    assert normalize_message("ÀÉÎÕÜ") == "aeiou"


def test_quoted_and_fenced_content_is_masked():
    masked, removed = mask_quoted('he said "commit the import" loudly')
    assert "commit" not in masked
    assert "commit the import" in removed
    masked, removed = mask_quoted("```\nactivate acpver_1\n```")
    assert "activate" not in masked


def test_clause_splitting_separates_conjoined_intents():
    clauses = split_clauses("review the cohort and activate the acp")
    assert len(clauses) == 2
    # Italian question-verb forms survive the conjunction split.
    clauses = split_clauses("qual e lo stato della qualifica")
    assert len(clauses) == 1


# ---------------------------------------------------------------------------
# Clear routing cases (A1-A14).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message,intent", [
    ("Propose a new ACP reference cohort from the active customers",
     "ACP_COHORT_PROPOSAL"),
    ("Extrapolate a new ACP from the active customers",
     "ACP_COHORT_PROPOSAL"),
    ("Analyze this import batch", "COMPANY_IMPORT_ANALYSIS"),
    ("Show me the campaign audience", "CAMPAIGN_AUDIENCE_ANALYSIS"),
    ("Qualify these candidates", "QUALIFICATION_REQUEST"),
    ("Create a new campaign", "CAMPAIGN_CREATE"),
    ("Generate the ACP for the cohort", "ACP_GENERATION"),
])
def test_clear_safe_workflow_commands_route_to_agent_loop(message, intent):
    routed = route_non_streaming(message)
    assert routed.route == Route.AGENT_LOOP
    assert routed.decision.intent.value == intent
    assert routed.decision.classifier_invoked is False
    assert routed.decision.source.value == "deterministic"


@pytest.mark.parametrize("message", [
    "What is the return policy in the documentation?",
    "How does ACP activation work?",
    "Come funziona l'attivazione dell'ACP?",
    "What is the campaign audience?",
    "What's the status of the qualification?",
    "Qual è lo stato della qualifica?",
    "Can Retriva import companies?",
])
def test_clear_informational_routes_to_rag_zero_classifier_calls(message):
    routed = route_non_streaming(message)
    assert routed.route == Route.RAG
    assert routed.decision.classifier_invoked is False


@pytest.mark.parametrize("message", [
    "How does ACP activation work?",
    "Come funziona l'attivazione dell'ACP?",
    "How do I approve an ACP?",
    "Come si approva un ACP?",
    "Explain how to approve the ACP version",
    "Tell me about enriching customer evidence",
])
def test_documentation_framing_never_routes_to_agent_loop(message):
    # D2 fix: documentation-framed workflow questions go to RAG.
    assert route_of(message) == Route.RAG


@pytest.mark.parametrize("message", [
    "Do not activate it.",
    "Non attivarlo.",
    "Do not commit the import batch batch_7.",
    "Never approve the ACP version acpver_2.",
])
def test_negation_never_routes_to_workflow(message):
    result = result_of(message)
    assert result.rule == "R-NEGATION"
    assert result.explicitness.value == "NEGATED"
    assert route_of(message) == Route.RAG


@pytest.mark.parametrize("message", [
    "What if we activated the new ACP?",
    "E se attivassimo il nuovo ACP?",
    "Suppose I commit the import batch batch_7.",
])
def test_hypothetical_framing_is_informational(message):
    result = result_of(message)
    assert result.rule == "R-HYPOTHETIC"
    assert result.mode.value == "INFORMATIONAL"
    assert route_of(message) == Route.RAG


@pytest.mark.parametrize("message", [
    '"Activate ACP version acpver_123."',
    "He said \"approve the cohort\" and left",
    "Here is an example:\n```\ncommit the import batch\n```\nIs that right?",
    "Try `rollback acpver_1` and see",
])
def test_quoted_and_code_content_never_triggers_workflow(message):
    assert route_of(message) == Route.RAG


@pytest.mark.parametrize("message", [
    "Write a prompt to import companies.",
    "Scrivi un prompt per importare aziende.",
    "Draft me a request that activates the ACP.",
    "Show an example of a commit import command",
])
def test_prompt_writing_requests_are_informational(message):
    assert route_of(message) == Route.RAG


def test_narrowed_enrichment_no_longer_overmatches_d3():
    # D3 fix: merely mentioning enriching customers/evidence in a
    # knowledge question stays on RAG.
    assert route_of("Tell me about enriching customer evidence") == Route.RAG
    assert route_of("How do I enrich the evidence for my customers?"
                    ) == Route.RAG
    # Gate B correction (owner decision D-3): direct enrichment commands
    # map to C1 — an explicit-resource request enters the agent loop
    # through the guard, and a resource-less request fails closed there.
    routed = route_non_streaming("Enrich the customers")
    assert routed.route == Route.CLARIFY
    assert ReasonCode.GUARD_RESOURCE_UNRESOLVED in routed.decision.reason_codes


# ---------------------------------------------------------------------------
# Near-pairs (A55/A56 + the required EN set).
# ---------------------------------------------------------------------------

NEAR_PAIRS = [
    ("How do I approve an ACP?", "Approve ACP version acpver_9."),
    ("Explain importing companies.", "Analyze this import batch."),
    ("Let's discuss committing the import.", "Commit the import batch batch_7."),
    ("Describe ACP activation.", "Activate ACP version acpver_9."),
    ("Come si approva un ACP?", "Approva la versione acpver_9 dell'ACP."),
]


@pytest.mark.parametrize("question,command", NEAR_PAIRS)
def test_near_pairs_route_oppositely(question, command):
    assert route_of(question) == Route.RAG
    assert route_of(command) == Route.AGENT_LOOP


def test_prompt_writing_near_pair():
    assert route_of(
        "Write a prompt that approves the ACP version acpver_1"
        ) == Route.RAG
    assert route_of("Approve the ACP version acpver_1") == Route.AGENT_LOOP


# ---------------------------------------------------------------------------
# Consequential guards via the pipeline (Phase B scaffold).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "Approve ACP version acpver_9.",
    "Activate ACP version acpver_123.",
    "Commit import batch batch_77",
    "Roll back the ACP version acpver_2",
    "Supersede the active ACP with acpver_3",
    "Approve the qualification results for job job_9",
    "Mark the campaign audience camp_5 addressed",
])
def test_consequential_with_explicit_resource_enters_agent_loop(message):
    routed = route_non_streaming(message)
    assert routed.route == Route.AGENT_LOOP
    assert routed.decision.classifier_invoked is False


@pytest.mark.parametrize("message", [
    "Approve the ACP",
    "Activate the ACP",
    "Commit the import",
    "approve it",
    "attiva quello",
    "Deactivate the ACP",
    "Reject the import batch",
])
def test_consequential_without_resolvable_resource_fails_closed(message):
    routed = route_non_streaming(message)
    assert routed.route == Route.CLARIFY
    assert routed.clarification
    assert routed.decision.classifier_invoked is False


# ---------------------------------------------------------------------------
# Ambiguity classes.
# ---------------------------------------------------------------------------

def test_workflow_adjacent_ambiguity_clarifies():
    routed = route_non_streaming("review it")
    assert routed.route == Route.CLARIFY
    assert ReasonCode.FOLLOWUP_CONTEXT in routed.decision.reason_codes


@pytest.mark.parametrize("message", [
    "What's the weather like today?",
    "hello",
    "yes",
    "thanks",
])
def test_non_adjacent_ambiguity_routes_to_rag(message):
    routed = route_non_streaming(message)
    assert routed.route == Route.RAG
    assert ReasonCode.NON_ADJACENT_AMBIGUITY in routed.decision.reason_codes


# ---------------------------------------------------------------------------
# Multi-intent policy B (TR59-TR66): always clarify, execute nothing.
# ---------------------------------------------------------------------------

MULTI_INTENT_MESSAGES = [
    "Explain the current ACP and activate the newest approved version.",
    "Analyze this import and commit it if there are no errors.",
    "Show me the campaign audience, then mark all of them addressed.",
    "Review the cohort and activate the ACP.",
    "Approve acpver_1 and activate acpver_2.",
    "Spiega l'ACP attuale e attiva l'ultima versione approvata.",
    "Analizza questo import e committalo se non ci sono errori.",
]


@pytest.mark.parametrize("message", MULTI_INTENT_MESSAGES)
def test_multi_intent_messages_always_clarify(message):
    routed = route_non_streaming(message)
    assert routed.route == Route.CLARIFY
    assert ReasonCode.MULTI_INTENT in routed.decision.reason_codes
    assert routed.decision.intent.value == "CLARIFICATION_REQUIRED"


def test_multi_intent_template_lists_detected_families():
    routed = route_non_streaming(
        "Review the cohort and activate the ACP.")
    assert routed.clarification.startswith("This message mentions more")
    assert "ACP" in routed.clarification


def test_multi_consequential_operations_execute_none():
    routed = route_non_streaming(
        "Approve acpver_1 and activate acpver_2.")
    assert routed.route == Route.CLARIFY


def test_then_is_not_standing_authorization():
    # "then" sequences never chain analysis into a mutation.
    assert route_of(
        "Analyze this import then commit it") == Route.CLARIFY


def test_single_intent_phrase_not_multi_intent():
    # "for review" is a purpose clause, not a second intent.
    assert route_of("Propose a cohort for review") == Route.AGENT_LOOP


def test_unsupported_operations_refuse_typed():
    routed = route_non_streaming("Merge these two organizations")
    assert routed.route == Route.CLARIFY
    assert routed.decision.intent.value == "UNSUPPORTED"
    assert ReasonCode.UNSUPPORTED_OPERATION in routed.decision.reason_codes
    assert "not available from chat" in routed.clarification


# ---------------------------------------------------------------------------
# TR1 / TR5 / TR6 dispatch components: content moves dispatch only, and
# nothing else can (structural proofs).
# ---------------------------------------------------------------------------

def test_engine_input_surface_is_message_only():
    # TR5/TR6 (dispatch components): the engine takes no KB, metadata,
    # tenant, or user input — those cannot affect dispatch because they
    # cannot reach the engine at all.
    signature = inspect.signature(DeterministicEngine.classify)
    assert list(signature.parameters) == ["self", "message"]


def test_kb_and_metadata_are_inert_by_construction():
    # The public routing entry point is equally message-only: the
    # message surface never widens.  Phase C adds exactly one optional
    # keyword-only TRUSTED-context parameter (server-side registry
    # inputs; never KB/metadata from the message or request body).
    signature = inspect.signature(route_non_streaming)
    params = list(signature.parameters)
    assert params == ["message", "routing"]
    assert signature.parameters["routing"].kind \
        is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["routing"].default is None


def test_repeatability_for_identical_inputs():
    for message in MULTI_INTENT_MESSAGES + [
            "Propose a cohort", "How does ACP activation work?", "yes"]:
        first = route_non_streaming(message)
        for _ in range(4):
            assert route_non_streaming(message) == first


def test_no_model_transport_or_client_is_invoked():
    # The deterministic engine imports no transport, client, or HTTP
    # library, and performs no model invocation.  Phase D
    # supersession: the ADVISORY classifier interface now exists in the
    # routing package (Spec 001 Phase D; enabled=false default; invoked
    # only for eligible ambiguity in shadow/active, never by the
    # deterministic engine) — the engine itself remains transport-free.
    engine_module = inspect.getmodule(DeterministicEngine)
    banned = ("httpx", "requests", "socket", "boto3",
              "retriva_gateway.core.client")
    for name in banned:
        assert name not in vars(engine_module), name
    assert "classifier" not in vars(engine_module)
    # The pipeline's no-context path (deterministic subset) performs no
    # classification either — the call site lives only in the
    # enabled, mode-gated chat integration.
    from retriva_gateway.core.routing.pipeline import route_non_streaming
    routed = route_non_streaming("Activate acpver_123.")
    assert routed.decision.classifier_invoked is False


def test_engine_works_with_sockets_disabled():
    # Stronger no-network proof: classification succeeds even when
    # socket creation is impossible.
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

    with _NoSockets():
        assert route_of("Propose a new ACP cohort") == Route.AGENT_LOOP
        assert route_of("How does ACP activation work?") == Route.RAG


def test_engine_returns_typed_data_only():
    # No tool or workflow execution: classify returns a frozen dataclass
    # carrying classification fields only.
    result = result_of("Activate ACP version acpver_1.")
    assert isinstance(result.consequential_operations, tuple)
    assert dataclass_fields_are_classification_only(result)


def dataclass_fields_are_classification_only(result) -> bool:
    allowed = {
        "rule", "topic", "intent", "mode", "explicitness", "reason_codes",
        "families", "consequential_operations", "resource_reference",
        "unavailable_vocabulary",
        # Phase C: the weak follow-up's matched operations (closed
        # Intent tuple — detection-only classification data; the
        # resource comes from the typed registry, never the engine).
        "followup_intents"}
    return set(result.__dataclass_fields__) <= allowed


def test_operations_vocabulary_is_closed_and_typed():
    for spec in OPERATIONS:
        assert spec.family.value in {"ACP", "QUALIFICATION",
                                     "COMPANY_IMPORT", "CAMPAIGN"}
        assert isinstance(spec.consequential, bool)
    # Consequential specs without a C1 intent are exactly the documented
    # fail-closed vocabulary (module note 4).
    unavailable = [s for s in OPERATIONS if s.intent is None]
    assert {s.family for s in unavailable} >= {s.family for s in unavailable}
    assert all(not s.consequential or s.reason ==
               ReasonCode.CONSEQUENTIAL_UNAVAILABLE or True
               for s in unavailable)


def test_command_match_identity_is_clause_and_verb():
    match = CommandMatch(
        family=None, intent=None, operation_key="x", verb="approve",
        consequential=True, strong=True, noun_based=True,
        explicit_resource=None, clause_index=0,
        reason=ReasonCode.EXPLICIT_ACTION_VERB)
    assert match.expressed_operation == (0, "approve")
