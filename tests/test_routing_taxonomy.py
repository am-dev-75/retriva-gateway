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

"""Closed taxonomy contracts (Spec 001 C1/C2/C3) — Phase B proof.

Proves the closed-vocabulary invariants: unknown schema versions,
unknown enum values, and extra fields are rejected; confidence is
strictly bounded and rejects NaN, infinities, and string typing; the
field sets are EXACTLY the accepted contract sets (no provider, model,
endpoint, region, credential, security, route-execution, authorization,
or tool field can appear); serialization is deterministic.
"""

import math

import pytest
from pydantic import ValidationError

from retriva_gateway.core.routing.taxonomy import (
    SCHEMA_VERSION,
    DecisionSource,
    Explicitness,
    Intent,
    IntentClassification,
    InteractionMode,
    ReasonCode,
    Route,
    RoutingDecision,
    Topic,
)

# The accepted C1 intent vocabulary, verbatim from the spec contract.
ACCEPTED_INTENTS = {
    "RAG_QUESTION", "WORKFLOW_DOCUMENTATION", "STATUS_EXPLANATION",
    "CAPABILITY_QUESTION",
    "ACP_COHORT_PROPOSAL", "ACP_COHORT_REVIEW", "ACP_COHORT_APPROVAL",
    "ACP_GENERATION", "ACP_REVIEW", "ACP_APPROVAL", "ACP_ACTIVATION",
    "ACP_SUPERSESSION", "ACP_ROLLBACK", "ACP_STATUS", "ACP_LINEAGE",
    "QUALIFICATION_REQUEST", "QUALIFICATION_STATUS",
    "QUALIFICATION_REVIEW", "QUALIFICATION_APPROVAL",
    "COMPANY_IMPORT_ANALYSIS", "COMPANY_IMPORT_REVIEW",
    "COMPANY_IMPORT_APPROVAL", "COMPANY_IMPORT_COMMIT",
    "COMPANY_IMPORT_STATUS",
    "CAMPAIGN_CREATE", "CAMPAIGN_AUDIENCE_ANALYSIS",
    "CAMPAIGN_AUDIENCE_REVIEW", "CAMPAIGN_AUDIENCE_APPROVAL",
    "CAMPAIGN_AUDIENCE_COMMIT", "CAMPAIGN_HISTORY_IMPORT",
    "CAMPAIGN_MARK_ADDRESSED", "CAMPAIGN_OUTCOME_UPDATE",
    "CAMPAIGN_STATUS",
    "AMBIGUOUS", "UNSUPPORTED", "CLARIFICATION_REQUIRED",
}

ACCEPTED_TOPICS = {"ACP", "QUALIFICATION", "COMPANY_IMPORT", "CAMPAIGN",
                   "DOCUMENTATION", "GENERAL"}
ACCEPTED_MODES = {"INFORMATIONAL", "ANALYSIS", "REVIEW", "MUTATION",
                  "DESTRUCTIVE_MUTATION", "UNKNOWN"}
ACCEPTED_EXPLICITNESS = {"EXPLICIT", "IMPLICIT", "AMBIGUOUS", "NEGATED",
                         "HYPOTHETICAL", "QUOTED_EXAMPLE"}
ACCEPTED_ROUTES = {"AGENT_LOOP", "RAG", "CLARIFY", "REFUSE_STREAM",
                   "LEGACY_RAG"}
ACCEPTED_SOURCES = {"deterministic", "classifier", "guard", "fail_closed"}


def test_c1_intent_vocabulary_is_exactly_the_accepted_set():
    assert {i.value for i in Intent} == ACCEPTED_INTENTS


def test_c1_topic_mode_explicitness_route_source_sets_are_closed():
    assert {t.value for t in Topic} == ACCEPTED_TOPICS
    assert {m.value for m in InteractionMode} == ACCEPTED_MODES
    assert {e.value for e in Explicitness} == ACCEPTED_EXPLICITNESS
    assert {r.value for r in Route} == ACCEPTED_ROUTES
    assert {s.value for s in DecisionSource} == ACCEPTED_SOURCES


def test_schema_version_is_one():
    assert SCHEMA_VERSION == "1"


def _valid_classification() -> dict:
    return {
        "schema_version": "1",
        "topic": "ACP",
        "intent": "ACP_ACTIVATION",
        "mode": "MUTATION",
        "explicitness": "EXPLICIT",
        "confidence": 0.9,
        "requires_clarification": False,
        "language": "en",
        "reason_codes": ["EXPLICIT_ACTION_VERB"],
    }


def test_valid_classification_roundtrip():
    model = IntentClassification(**_valid_classification())
    assert model.schema_version == "1"
    data = model.model_dump()
    assert data["topic"] == "ACP"
    again = IntentClassification.model_validate_json(model.model_dump_json())
    assert again == model


def test_unknown_schema_version_rejected():
    payload = _valid_classification() | {"schema_version": "2"}
    with pytest.raises(ValidationError):
        IntentClassification(**payload)


@pytest.mark.parametrize("field,bad", [
    ("topic", "MARKETING"),
    ("intent", "ACP_DELETION"),
    ("mode", "DELETION"),
    ("explicitness", "UNCLEAR"),
])
def test_unknown_enum_values_rejected(field, bad):
    payload = _valid_classification() | {field: bad}
    with pytest.raises(ValidationError):
        IntentClassification(**payload)


def test_extra_fields_rejected():
    payload = _valid_classification() | {"provider": "openrouter"}
    with pytest.raises(ValidationError):
        IntentClassification(**payload)
    payload = _valid_classification() | {"authorize": True}
    with pytest.raises(ValidationError):
        IntentClassification(**payload)
    decision = dict(
        route="RAG", source="deterministic", topic="GENERAL",
        intent="RAG_QUESTION", mode="INFORMATIONAL",
        explicitness="IMPLICIT", reason_codes=[])
    with pytest.raises(ValidationError):
        RoutingDecision(**(decision | {"tool_arguments": {}}))


@pytest.mark.parametrize("bad", [
    1.5, -0.01, math.nan, math.inf, -math.inf, "0.9", True, None,
])
def test_confidence_bounds_and_types_enforced(bad):
    payload = _valid_classification() | {"confidence": bad}
    with pytest.raises(ValidationError):
        IntentClassification(**payload)


def test_confidence_boundary_values_accepted():
    for edge in (0.0, 1.0):
        model = IntentClassification(
            **_valid_classification() | {"confidence": edge})
        assert model.confidence == edge


def test_reason_codes_closed_and_bounded():
    payload = _valid_classification() | {"reason_codes": ["NOT_A_REASON"]}
    with pytest.raises(ValidationError):
        IntentClassification(**payload)
    payload = _valid_classification() | {
        "reason_codes": ["NO_DETERMINISTIC_MATCH"] * 9}
    with pytest.raises(ValidationError):
        IntentClassification(**payload)


# The exact accepted field sets — no authority, provider, or transport
# field can ever appear in these contracts (Spec 001 C2/C3, §11).
C2_FIELDS = {
    "schema_version", "topic", "intent", "mode", "explicitness",
    "confidence", "requires_clarification", "clarification_reason",
    "resource_reference", "language", "reason_codes",
}
C3_FIELDS = {
    "route", "source", "topic", "intent", "mode", "explicitness",
    "confidence", "reason_codes", "classifier_invoked", "shadow",
}
FORBIDDEN_FIELD_MARKERS = (
    "provider", "model", "endpoint", "region", "residency", "credential",
    "secret", "api_key", "base_url", "security", "authorize",
    "authorization", "permission", "tool", "route_into", "execute",
    "execution_plan", "plan", "arguments", "tenant_id", "user_id",
)


def test_field_sets_are_exactly_the_accepted_contracts():
    assert set(IntentClassification.model_fields) == C2_FIELDS
    assert set(RoutingDecision.model_fields) == C3_FIELDS


@pytest.mark.parametrize("fields", [C2_FIELDS, C3_FIELDS],
                         ids=["C2", "C3"])
def test_no_authority_or_transport_field_can_be_added(fields):
    # The closed sets exclude every forbidden domain; adding any such
    # field name would have to change these asserted sets.
    for field in fields:
        assert not any(marker in field for marker in FORBIDDEN_FIELD_MARKERS)


def test_routing_decision_deterministic_defaults():
    decision = RoutingDecision(
        route=Route.RAG, source=DecisionSource.DETERMINISTIC,
        topic=Topic.GENERAL, intent=Intent.RAG_QUESTION,
        mode=InteractionMode.INFORMATIONAL,
        explicitness=Explicitness.IMPLICIT, reason_codes=[])
    # Phase B: no classifier exists — every deterministic decision
    # carries no confidence and never claims a classifier invocation.
    assert decision.confidence is None
    assert decision.classifier_invoked is False
    assert decision.shadow is False
    assert RoutingDecision.model_validate_json(
        decision.model_dump_json()) == decision
