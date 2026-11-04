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

"""Spec 040 Phase B — strict SC2 contract validation tests."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from retriva_gateway.core.routing.cards import derive_cards
from retriva_gateway.core.routing.schema import (
    FAMILIES,
    MAX_REASON_CODES,
    Family,
    SemanticRouteDecisionV2,
)


def _payload(**overrides):
    payload = {
        "schema_version": "2",
        "prompt_version": "2",
        "decision": "RAG",
        "family": None,
        "confidence": 0.91,
        "requires_clarification": False,
        "language": "en",
        "reason_codes": ["NO_DETERMINISTIC_MATCH"],
    }
    payload.update(overrides)
    return payload


def _valid(**overrides):
    return SemanticRouteDecisionV2.model_validate(_payload(**overrides))


def test_family_enum_is_generated_from_the_cards():
    assert set(FAMILIES) == {card.family for card in derive_cards()}
    assert set(Family.__members__) == set(FAMILIES)


def test_valid_rag_decision():
    decision = _valid()
    assert decision.decision.value == "RAG"
    assert decision.family is None
    assert decision.schema_version == "2"
    assert decision.prompt_version == "2"


def test_valid_family_decision_for_each_card():
    for family in sorted(FAMILIES):
        decision = _valid(decision="FAMILY", family=family)
        assert decision.family.value == family
        assert decision.requires_clarification is False


def test_valid_clarify_decision():
    decision = _valid(decision="CLARIFY", requires_clarification=True,
                      reason_codes=["NO_DETERMINISTIC_MATCH"])
    assert decision.decision.value == "CLARIFY"
    assert decision.family is None


@pytest.mark.parametrize("extra", [
    "tool", "operation", "resource_id", "tenant_id", "session_id",
    "authorization", "route", "plan", "arguments",
])
def test_unknown_and_forbidden_fields_are_rejected(extra):
    with pytest.raises(ValidationError):
        _valid(**{extra: "x"})


@pytest.mark.parametrize("confidence", [
    -0.01, 1.01, float("nan"), float("inf"), float("-inf"), "0.9", True,
])
def test_confidence_must_be_a_finite_bounded_number(confidence):
    with pytest.raises(ValidationError):
        _valid(confidence=confidence)


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
def test_confidence_bounds_are_inclusive(confidence):
    assert _valid(confidence=confidence).confidence == confidence


@pytest.mark.parametrize("family", [
    "GENERAL", "DOCUMENTATION", "MADE_UP", "campaign", 123,
])
def test_family_not_in_cards_is_rejected(family):
    with pytest.raises(ValidationError):
        _valid(decision="FAMILY", family=family)


def test_family_requires_a_family():
    with pytest.raises(ValidationError):
        _valid(decision="FAMILY", family=None)


@pytest.mark.parametrize("decision", ["RAG", "CLARIFY"])
def test_non_family_decisions_must_not_carry_a_family(decision):
    with pytest.raises(ValidationError):
        _valid(decision=decision, family="CAMPAIGN",
               requires_clarification=(decision == "CLARIFY"))


@pytest.mark.parametrize("version_field", [
    "schema_version", "prompt_version",
])
@pytest.mark.parametrize("value", ["1", "3", 2, ""])
def test_version_literals_are_enforced(version_field, value):
    with pytest.raises(ValidationError):
        _valid(**{version_field: value})


def test_clarify_requires_the_clarification_flag():
    with pytest.raises(ValidationError):
        _valid(decision="CLARIFY", requires_clarification=False)


@pytest.mark.parametrize("decision", ["RAG", "FAMILY"])
def test_non_clarify_requires_the_flag_to_be_false(decision):
    with pytest.raises(ValidationError):
        _valid(decision=decision, family=(
            "CAMPAIGN" if decision == "FAMILY" else None),
            requires_clarification=True)


@pytest.mark.parametrize("language", ["fr", "EN", "it-IT", ""])
def test_language_is_closed(language):
    with pytest.raises(ValidationError):
        _valid(language=language)


def test_unknown_reason_codes_are_rejected():
    with pytest.raises(ValidationError):
        _valid(reason_codes=["NOT_A_REASON_CODE"])


def test_reason_codes_are_bounded():
    with pytest.raises(ValidationError):
        _valid(reason_codes=["NO_DETERMINISTIC_MATCH"] * (MAX_REASON_CODES + 1))


def test_contract_has_no_defaults_for_required_fields():
    for field in ("schema_version", "prompt_version", "decision",
                  "confidence", "requires_clarification", "language"):
        payload = _payload()
        payload.pop(field)
        with pytest.raises(ValidationError):
            SemanticRouteDecisionV2.model_validate(payload)


def test_non_finite_confidence_is_rejected_even_if_math_reports_finite():
    # Guard against a validator accidentally accepting NaN via a default.
    with pytest.raises(ValidationError):
        _valid(confidence=math.nan)
