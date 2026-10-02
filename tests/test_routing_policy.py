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

"""Spec 001 Phase E — decision policy tests (core/routing/policy.py).

Covers: confidence semantics (inclusive >=, closed buckets), the
route-neutral shadow application (Phase D/C3 decision annotation
contract), the narrow active authority (informational -> RAG,
safe-workflow -> agent loop at/above threshold, consequential ->
ALWAYS clarify with no threshold path, clarification selection uses
the deterministic template), and the shadow diagnostics ring
(bounded, ephemeral, content-free).  Deterministic fakes only — no
classifier call, no live endpoint.
"""

from __future__ import annotations

import time

from retriva_gateway.core.routing import (
    Route,
    apply_active,
    apply_classification,
    apply_shadow,
    classification_context_hints,
    classifier_config_from_settings,
    confidence_bucket,
    confidence_meets,
    route_non_streaming,
    shadow_diagnostics_ring,
)
from retriva_gateway.core.routing.classifier import IntentClassification
from retriva_gateway.core.routing.taxonomy import Intent
from retriva_gateway.core.routing.classifier import IntentClassification
from retriva_gateway.core.routing.policy import (
    CONFIDENCE_BUCKETS,
    ShadowDiagnostic,
    build_shadow_diagnostic,
    reset_shadow_ring_for_tests,
)


def _routed(message="Handle the import."):
    return route_non_streaming(message)


def _c2(**overrides):
    base = {
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
    return IntentClassification.model_validate({**base, **overrides})


# ---------------------------------------------------------------------------
# Confidence semantics
# ---------------------------------------------------------------------------

def test_confidence_meets_is_inclusive():
    assert confidence_meets(0.85, 0.85) is True
    assert confidence_meets(0.90, 0.90) is True
    assert confidence_meets(0.84, 0.85) is False
    assert confidence_meets(1.0, 0.90) is True


def test_confidence_bucket_closed_labels():
    # Below 0.50 has its own closed bucket; never an unbounded label.
    assert confidence_bucket(0.40) == "bucket_below_0.50"
    assert confidence_bucket(0.50) == "bucket_0.50_0.70"
    assert confidence_bucket(0.69) == "bucket_0.50_0.70"
    assert confidence_bucket(0.70) == "bucket_0.70_0.85"
    assert confidence_bucket(0.84) == "bucket_0.70_0.85"
    assert confidence_bucket(0.85) == "bucket_0.85_1.00"
    assert confidence_bucket(1.0) == "bucket_0.85_1.00"
    # Every bucket name is drawn from the closed set.
    names = {b[0] for b in CONFIDENCE_BUCKETS} | {"bucket_below_0.50"}
    for v in (0.40, 0.55, 0.75, 0.95):
        assert confidence_bucket(v) in names


# ---------------------------------------------------------------------------
# Shadow: route-neutral + decision annotation contract
# ---------------------------------------------------------------------------

def test_shadow_keeps_route_and_annotates_decision():
    routed = _routed()
    config = classifier_config_from_settings()
    classification = _c2(intent="RAG_QUESTION", topic="GENERAL",
                         mode="INFORMATIONAL", confidence=0.95)
    shadow = apply_classification(
        routed, classification, mode="shadow", config=config)
    # Route-neutral: the deterministic route is unchanged.
    assert shadow.route is routed.route
    assert shadow.decision.classifier_invoked is True
    assert shadow.decision.shadow is True
    assert shadow.decision.confidence == 0.95
    # The free-form classifier text was never executed — the Gateway
    # keeps its own deterministic clarification.
    assert shadow.clarification == routed.clarification


def test_shadow_failure_records_diagnostic_keeps_route():
    reset_shadow_ring_for_tests()
    routed = _routed()
    ring = shadow_diagnostics_ring()
    before = ring.summary()["records"]
    shadow = apply_shadow(routed, None, failure_category="timeout",
                          latency_s=0.012)
    # Deterministically degraded: the routed result stands unchanged.
    assert shadow is routed
    assert ring.summary()["records"] == before + 1


# ---------------------------------------------------------------------------
# Active: narrow authority only
# ---------------------------------------------------------------------------

def test_active_informational_resolves_to_rag_above_threshold():
    routed = _routed()
    config = classifier_config_from_settings()
    classification = _c2(intent="RAG_QUESTION", topic="GENERAL",
                         mode="INFORMATIONAL", confidence=0.95)
    active = apply_classification(
        routed, classification, mode="active", config=config)
    assert active.route is Route.RAG
    assert active.decision.classifier_invoked is True
    assert active.decision.shadow is False


def test_active_informational_below_threshold_clarifies():
    routed = _routed()
    config = classifier_config_from_settings()
    classification = _c2(intent="RAG_QUESTION", topic="GENERAL",
                         mode="INFORMATIONAL", confidence=0.60)
    active = apply_classification(
        routed, classification, mode="active", config=config)
    assert active.route is Route.CLARIFY
    assert active.clarification


def test_active_consequential_always_clarifies_no_threshold_path():
    routed = _routed()
    config = classifier_config_from_settings()
    # High confidence must NOT open a consequential path.
    for confidence in (0.99, 0.95, 0.90, 0.85, 0.70):
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
    # >= min_confidence (0.85) but < safe_workflow (0.90).
    classification = _c2(intent="ACP_COHORT_REVIEW", topic="ACP",
                         mode="ANALYSIS", confidence=0.88)
    active = apply_classification(
        routed, classification, mode="active", config=config)
    assert active.route is Route.CLARIFY


def test_active_clarification_uses_deterministic_template():
    routed = _routed()
    config = classifier_config_from_settings()
    # requires_clarification with free-form text — the Gateway MUST use
    # its own deterministic template, never execute the classifier text.
    classification = _c2(
        intent="ACP_COHORT_REVIEW", topic="ACP", mode="ANALYSIS",
        confidence=0.95, requires_clarification=True,
        clarification_reason="do not execute this text")
    active = apply_classification(
        routed, classification, mode="active", config=config)
    assert active.route is Route.CLARIFY
    assert "do not execute this text" not in active.clarification


# ---------------------------------------------------------------------------
# Shadow diagnostics: bounded, ephemeral, content-free
# ---------------------------------------------------------------------------

def test_fr1_active_consequential_clarification_no_crash():
    # PHASEF-DEFECT-1: apply_active for a consequential classification with a
    # routed decision that carries NO prebuilt clarification must not raise and
    # must preserve the accepted CLARIFY outcome (build_clarification now
    # receives a DeterministicResult, never a bare list).
    routed = route_non_streaming("Activate acpver_123.")
    assert routed.clarification is None  # precondition for the fixed branch
    config = classifier_config_from_settings()
    classification = _c2(intent="ACP_ACTIVATION", topic="ACP",
                         mode="MUTATION", confidence=0.95,
                         requires_clarification=True)
    active = apply_active(routed, classification, config)
    assert active.route is Route.CLARIFY
    assert active.decision.intent is Intent.CLARIFICATION_REQUIRED
    assert active.clarification is not None
    # No agent-loop admission, no tool execution, no registry/confirmation
    # mutation.
    assert active.decision.shadow is False
    assert routed.claimed is None


def test_shadow_diagnostic_allowlisted_fields_only():
    routed = _routed()
    classification = _c2(confidence=0.92, intent="ACP_APPROVAL",
                         topic="ACP", mode="MUTATION")
    diag = build_shadow_diagnostic(
        routed=routed, classification=classification,
        latency_s=0.02, deployment_mode="shadow")
    assert isinstance(diag, ShadowDiagnostic)
    # The allowlisted fields only — serialize and confirm no leakage of
    # message/prompt/token/identifier content.
    blob = str(diag.__dict__)
    for forbidden in ("acpver", "token", "claim", "idempotency",
                      "secret", "key", "Bearer"):
        assert forbidden not in blob
    assert diag.confidence_bucket == "bucket_0.85_1.00"
    assert diag.deterministic_route_category == routed.route.value


def test_shadow_ring_is_bounded_and_ephemeral():
    reset_shadow_ring_for_tests()
    ring = shadow_diagnostics_ring()
    routed = _routed()
    for _ in range(1500):
        ring.push(build_shadow_diagnostic(routed=routed))
    summary = ring.summary()
    assert summary["capacity"] == 1000
    assert summary["records"] == 1000
    assert summary["ttl_seconds"] == 900.0


def test_shadow_ring_purges_expired_first():
    reset_shadow_ring_for_tests()
    ring = shadow_diagnostics_ring()
    routed = _routed()
    # Seed an old record (TTL 900s) then a fresh batch.
    old = build_shadow_diagnostic(routed=routed)
    old = ShadowDiagnostic(**{**old.__dict__, "timestamp": time.time() - 1000})
    ring.push(old)
    for _ in range(5):
        ring.push(build_shadow_diagnostic(routed=routed))
    # The single expired record is purged before counting.
    assert ring.summary()["records"] == 5
