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

"""Gateway-owned routing decision policy (Spec 001 Phase E;
architecture §7).

This module owns the accepted closed decision tables for shadow mode,
active mode, classifier-disabled behavior, classifier-unavailable
behavior, confidence thresholds, deterministic degradation, and the
consequential-operation prohibitions.  It owns NO provider transport,
model transport, prompt construction, Core endpoint access,
WorkflowContext persistence, confirmation creation or claims, domain
authorization, tool execution, or streaming transport.

Precedence is enforced upstream (the pipeline/chat integration):
mode off -> streaming gate -> deterministic routing -> multi-intent
Policy B -> Phase C confirmation paths -> deterministic guards ->
eligible ambiguity -> this policy -> failure degradation.  Classifier
recommendations can never move ahead of deterministic vetoes,
multi-intent handling, confirmation claims, or guards.

Confidence semantics: inclusive ``>=`` comparisons against the
process-global thresholds (informational 0.85, safe workflow 0.90 —
validated at startup); NO consequential threshold path exists in code
(structurally: the only agent-loop path for ambiguity is gated on a
non-consequential intent, and the consequential branch returns
clarification before any threshold is read).  High confidence cannot
override negation, hypothetical, quotation, code, or prompt-writing
vetoes, multi-intent Policy B, deterministic guards, or Phase C
confirmation rules — those precede this module and are terminal.

Shadow mode: route-neutral — the deterministic route is NEVER altered
by classifier output; only the accepted privacy-safe diagnostic record
is produced (allowlisted fields only, confidence BUCKETS never raw,
ephemeral bounded ring, no persistence).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from .guards import CONSEQUENTIAL_INTENTS
from .taxonomy import (
    DecisionSource,
    Explicitness,
    Intent,
    InteractionMode,
    ReasonCode,
    Route,
    RoutingDecision,
)

# ---------------------------------------------------------------------------
# Confidence semantics (Spec 001 C7 / Phase E; process-global)
# ---------------------------------------------------------------------------

INFORMATIONAL_THRESHOLD = 0.85
SAFE_WORKFLOW_THRESHOLD = 0.90

#: The only intents the active table may ever route into the agent
#: loop — SAFE, non-consequential workflow operations (ambiguous
#: non-destructive analysis and proposal creation; the accepted
#: narrowed authority).  Consequential intents are structurally
#: absent: there is NO threshold path to a consequential route.
_SAFE_WORKFLOW_INTENTS = frozenset({
    Intent.ACP_COHORT_PROPOSAL, Intent.ACP_COHORT_REVIEW,
    Intent.ACP_GENERATION, Intent.ACP_REVIEW, Intent.ACP_STATUS,
    Intent.ACP_LINEAGE,
    Intent.QUALIFICATION_REQUEST, Intent.QUALIFICATION_STATUS,
    Intent.QUALIFICATION_REVIEW,
    Intent.COMPANY_IMPORT_ANALYSIS, Intent.COMPANY_IMPORT_STATUS,
    Intent.CAMPAIGN_CREATE, Intent.CAMPAIGN_AUDIENCE_ANALYSIS,
    Intent.CAMPAIGN_STATUS,
})

_INFORMATIONAL_INTENTS = (
    Intent.RAG_QUESTION, Intent.WORKFLOW_DOCUMENTATION,
    Intent.STATUS_EXPLANATION, Intent.CAPABILITY_QUESTION)

#: Consequential members (TR32-TR39): every ambiguous classification
#: with one of these intents clarifies REGARDLESS of confidence.
_CONSEQUENTIAL = frozenset(CONSEQUENTIAL_INTENTS)


def confidence_meets(value: float, threshold: float) -> bool:
    """Inclusive comparison: value >= threshold (exact boundary follows
    the recommendation — TR40)."""
    return float(value) >= float(threshold)


def is_safe_workflow(intent: Intent) -> bool:
    """True only for the accepted safe, non-consequential workflow
    intents (analysis/proposal) — never a consequential member."""
    return intent in _SAFE_WORKFLOW_INTENTS


def is_consequential(intent: Intent) -> bool:
    return intent in _CONSEQUENTIAL


# ---------------------------------------------------------------------------
# Shadow diagnostic record (exact accepted allowlist; §Shadow-mode
# privacy) — closed, content-free, ephemeral.
# ---------------------------------------------------------------------------

#: Accepted confidence buckets (bounded labels; never raw confidence).
CONFIDENCE_BUCKETS = (
    ("bucket_0.50_0.70", 0.50, 0.70),
    ("bucket_0.70_0.85", 0.70, 0.85),
    ("bucket_0.85_1.00", 0.85, 1.01),
)
_BELOW_THRESHOLD_BUCKET = "bucket_below_0.50"


def confidence_bucket(value: float) -> str:
    """Closed bounded bucket for a validated confidence value; values
    below 0.50 (invalid/low-confidence policy) get their own closed
    bucket — never an unbounded label."""
    for name, low, high in CONFIDENCE_BUCKETS:
        if low <= value < high:
            return name
    return _BELOW_THRESHOLD_BUCKET


@dataclass(frozen=True)
class ShadowDiagnostic:
    """Exactly the accepted allowlisted fields — nothing else.  Never
    the message, prompt text, full response, free-form clarification
    text, tenant/principal/session/KB/resource identifiers,
    WorkflowContext or PendingConfirmation content, tokens, claim IDs,
    idempotency keys, tool arguments, provider error bodies, API keys,
    or endpoint URLs."""

    schema_version: str
    prompt_version: str
    config_fingerprint: str
    deterministic_route_category: str
    classifier_recommendation_category: str
    workflow_family: str
    interaction_mode: str
    explicitness_class: str
    agree: Optional[bool]
    confidence_bucket: str
    reason_codes: Tuple[str, ...]
    latency_s: Optional[float]
    regional_policy_result: str
    safe_error_category: str
    timestamp: float
    deployment_mode: str


class ShadowDiagnosticsRing:
    """Ephemeral, process-local, bounded ring (architecture §10):
    capacity 1000, TTL 15 minutes, expired-first purge, lost on
    restart, no persistence, no export beyond the authenticated
    content-free status summary (counts + expiry only).  No download,
    query, search, or retention API exists."""

    def __init__(self, capacity: int = 1000,
                 ttl_seconds: float = 900.0) -> None:
        self._capacity = int(capacity)
        self._ttl = float(ttl_seconds)
        self._lock = threading.Lock()
        self._records: list = []

    def _purge_expired_locked(self, now: float) -> None:
        self._records = [r for r in self._records
                         if (now - r.timestamp) < self._ttl]

    def push(self, record: ShadowDiagnostic) -> None:
        now = time.time()
        with self._lock:
            self._purge_expired_locked(now)
            self._records.append(record)
            if len(self._records) > self._capacity:
                # Expired-first purge already ran; dropping the oldest
                # preserves the bounded capacity (FIFO bound).
                self._records = self._records[-self._capacity:]

    def summary(self) -> dict:
        """Content-free status: counts and expiry only — never
        individual records."""
        now = time.time()
        with self._lock:
            self._purge_expired_locked(now)
            return {
                "records": len(self._records),
                "capacity": self._capacity,
                "ttl_seconds": self._ttl,
            }


_RING = ShadowDiagnosticsRing()


def shadow_diagnostics_ring() -> ShadowDiagnosticsRing:
    return _RING


def reset_shadow_ring_for_tests() -> ShadowDiagnosticsRing:
    global _RING
    _RING = ShadowDiagnosticsRing()
    return _RING


def build_shadow_diagnostic(
        *, routed, classification=None, failure_category: str = "",
        latency_s: Optional[float] = None,
        config_fingerprint: str = "",
        prompt_version: str = "1",
        regional_policy_result: str = "not_applicable",
        deployment_mode: str = "shadow") -> ShadowDiagnostic:
    """Build the closed diagnostic record from the deterministic route
    and the validated (advisory) classification or the typed failure
    category — allowlisted fields only."""
    decision = routed.decision
    recommendation = "unavailable" if classification is None \
        else classification.intent.value
    if failure_category:
        recommendation = f"error:{failure_category}"
    agree = None
    if classification is not None:
        agree = (
            (classification.intent is decision.intent)
            if decision.intent is not Intent.AMBIGUOUS else None)
    return ShadowDiagnostic(
        schema_version="1",
        prompt_version=prompt_version,
        config_fingerprint=config_fingerprint,
        deterministic_route_category=routed.route.value,
        classifier_recommendation_category=recommendation,
        workflow_family=classification.topic.value
        if classification is not None else "unknown",
        interaction_mode=classification.mode.value
        if classification is not None else "UNKNOWN",
        explicitness_class=classification.explicitness.value
        if classification is not None
        else decision.explicitness.value,
        agree=agree,
        confidence_bucket=confidence_bucket(
            classification.confidence)
        if classification is not None else _BELOW_THRESHOLD_BUCKET,
        reason_codes=tuple(
            r.value for r in (classification.reason_codes
                              if classification is not None
                              else ())),
        latency_s=latency_s,
        regional_policy_result=regional_policy_result,
        safe_error_category=failure_category,
        timestamp=time.time(),
        deployment_mode=deployment_mode,
    )


# ---------------------------------------------------------------------------
# Policy application (shadow: route-neutral; active: narrow authority)
# ---------------------------------------------------------------------------

def apply_shadow(routed, classification=None, *, failure_category: str = "",
                 latency_s: Optional[float] = None,
                 config_fingerprint: str = "",
                 prompt_version: str = "1") -> object:
    """Shadow mode: run the deterministic route UNCHANGED, record only
    the accepted privacy-safe diagnostic.  Classifier output can never
    alter the route, guard result, clarification requirement, or
    admission (TR56 route neutrality).  The decision record carries
    only the safe structured annotation (classifier_invoked, shadow,
    confidence) — the Phase D/C3 decision contract."""
    ring = shadow_diagnostics_ring()
    ring.push(build_shadow_diagnostic(
        routed=routed, classification=classification,
        failure_category=failure_category, latency_s=latency_s,
        config_fingerprint=config_fingerprint,
        prompt_version=prompt_version,
        deployment_mode="shadow"))
    if classification is None:
        return routed
    from .pipeline import PhaseBChatRoute
    decision = routed.decision
    return PhaseBChatRoute(
        route=routed.route,
        decision=RoutingDecision(
            route=decision.route,
            source=decision.source,
            topic=decision.topic,
            intent=decision.intent,
            mode=decision.mode,
            explicitness=decision.explicitness,
            confidence=classification.confidence,
            reason_codes=tuple(decision.reason_codes),
            classifier_invoked=True,
            shadow=True),
        clarification=routed.clarification,
        claimed=routed.claimed,
        resolved=routed.resolved)


def apply_active(routed, classification, config) -> object:
    """Active mode: the accepted NARROW authority only (architecture
    §7 active rows; spec §Active-mode classifier authority).

    1. Ambiguous informational — confidence >= informational
       threshold (0.85): RAG; lower: clarification.
    2. Ambiguous non-destructive analysis / proposal creation — a SAFE
       workflow intent at or above the safe-workflow threshold (0.90):
       agent loop; lower: clarification.
    3. Clarification selection — the classifier may recommend the
       closed clarification category; the Gateway selects the
       deterministic template (free-form instructions never execute).
    4. Every ambiguous CONSEQUENTIAL classification clarifies,
       regardless of confidence — there is no threshold path (the
       consequential branch returns before any threshold comparison).
    """
    if is_consequential(classification.intent):
        # No threshold is read for a consequential intent (TR32-39).
        return _clarification(routed, classification)

    if classification.requires_clarification:
        # Clarification selection: the recommendation category is
        # honored as a CLOSED clarification choice — the deterministic
        # template, never free-form classifier text.
        return _clarification(routed, classification)

    if classification.intent in _INFORMATIONAL_INTENTS:
        if confidence_meets(classification.confidence,
                            config.min_confidence):
            return _rag(routed, classification)
        return _clarification(routed, classification)

    if is_safe_workflow(classification.intent):
        if confidence_meets(classification.confidence,
                            config.safe_workflow_min_confidence):
            return _agent_loop(routed, classification)
        return _clarification(routed, classification)

    # Anything else (unknown/unsupported/contradictory shapes that
    # passed validation) clarifies — fail closed.
    return _clarification(routed, classification)


def apply_classification(routed, classification, *, mode: str,
                         config) -> object:
    """The Phase D entry point, preserved: dispatch to the shadow
    (route-neutral) or active (narrow authority) table."""
    if mode == "shadow":
        return apply_shadow(routed, classification)
    return apply_active(routed, classification, config)


# -- deterministic route constructors (closed) ------------------------------

def _decision(routed, classification, route: Route,
              reason_codes: Tuple[ReasonCode, ...]) -> RoutingDecision:
    return RoutingDecision(
        route=route,
        source=DecisionSource.GUARD,
        topic=classification.topic,
        intent=classification.intent,
        mode=classification.mode,
        explicitness=classification.explicitness,
        confidence=classification.confidence,
        reason_codes=reason_codes,
        classifier_invoked=True,
        shadow=False)


def _rag(routed, classification):
    from .pipeline import PhaseBChatRoute
    return PhaseBChatRoute(
        route=Route.RAG,
        decision=_decision(routed, classification, Route.RAG, (
            ReasonCode.NON_ADJACENT_AMBIGUITY
            if ReasonCode.NON_ADJACENT_AMBIGUITY
            in routed.decision.reason_codes
            else ReasonCode.WORKFLOW_ADJACENT,)))


def _agent_loop(routed, classification):
    from .pipeline import PhaseBChatRoute
    return PhaseBChatRoute(
        route=Route.AGENT_LOOP,
        decision=_decision(routed, classification, Route.AGENT_LOOP, (
            ReasonCode.WORKFLOW_ADJACENT,)))


def _clarification(routed, classification):
    """Clarification selection: the deterministic closed template —
    free-form classifier instructions never execute."""
    from .clarifications import build_clarification
    from .deterministic import DeterministicResult
    from .pipeline import PhaseBChatRoute
    reason = (ReasonCode.NON_ADJACENT_AMBIGUITY
              if ReasonCode.NON_ADJACENT_AMBIGUITY
              in routed.decision.reason_codes
              else ReasonCode.WORKFLOW_ADJACENT)
    clarification = routed.clarification
    if clarification is None:
        # Type-correct clarification synthesis: build_clarification requires a
        # DeterministicResult, never a bare list (F-R1).
        clarification = build_clarification(DeterministicResult(
            rule="R-CLARIFICATION",
            topic=classification.topic,
            intent=Intent.CLARIFICATION_REQUIRED,
            mode=InteractionMode.UNKNOWN,
            explicitness=classification.explicitness,
            reason_codes=(reason,),
            families=(classification.topic,),
            consequential_operations=(),
        ))
    decision = RoutingDecision(
        route=Route.CLARIFY,
        source=DecisionSource.GUARD,
        topic=classification.topic,
        intent=Intent.CLARIFICATION_REQUIRED,
        mode=InteractionMode.UNKNOWN,
        explicitness=classification.explicitness,
        confidence=classification.confidence,
        reason_codes=(reason,),
        classifier_invoked=True,
        shadow=False)
    return PhaseBChatRoute(
        route=Route.CLARIFY, decision=decision,
        clarification=clarification,
        claimed=routed.claimed,
        resolved=routed.resolved)
