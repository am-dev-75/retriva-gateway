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

"""Catalog-driven semantic router (Spec 040 Phase C; contracts SC1-SC5).

The semantic router is the ONLY component that chooses between the RAG
plane and a Company-Intelligence family for a non-command turn in the
Phase C input band.  It is strictly advisory in one dimension: it
selects a data plane and, for FAMILY, a catalog family.  It never
selects a tool, operation, resource, identity, session, tenant, or
write; the Gateway's read-only loop admission enforces that
structurally.

The deterministic safety layer remains upstream and terminal.  This
module has one call site (``route_semantic``); it never touches chat,
tools, the agent loop, a reranker, or another routing pass.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Deque, Dict, Optional, Tuple

from retriva_gateway.core.routing.cards import (
    CapabilityCard,
    derive_cards,
)
from retriva_gateway.core.routing.metrics import routing_metrics
from retriva_gateway.core.routing.schema import (
    SemanticRouteDecisionV2,
)
from retriva_gateway.core.routing.taxonomy import (
    Explicitness,
    Intent,
    ReasonCode,
)

#: Closed failure categories (Spec 040 SC5).  Every failure maps to
#: CLARIFY; there is no permissive fallback and no second model call.
class SemanticFailure(str, Enum):
    ROUTER_TIMEOUT = "router_timeout"
    ROUTER_UNAVAILABLE = "router_unavailable"
    ROUTER_INVALID_OUTPUT = "router_invalid_output"
    ROUTER_SCHEMA_MISMATCH = "router_schema_mismatch"
    ROUTER_UNKNOWN_FAMILY = "router_unknown_family"
    ROUTER_BELOW_THRESHOLD = "router_below_threshold"


class SemanticRouterError(Exception):
    def __init__(self, category: SemanticFailure) -> None:
        self.category = category
        super().__init__(category.value)


@dataclass(frozen=True)
class SemanticRouterConfig:
    enabled: bool = False
    min_confidence: float = 0.85
    family_min_confidence: float = 0.85
    timeout_seconds: float = 35.0
    max_input_chars: int = 2000

    def validate(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("AGENT_SEMANTIC_ROUTER_ENABLED must be bool")
        for name, value in (("min_confidence", self.min_confidence),
                            ("family_min_confidence",
                             self.family_min_confidence)):
            if not 0.50 <= float(value) <= 1.00:
                raise ValueError(
                    f"AGENT_SEMANTIC_ROUTER_{name.upper()} must be "
                    f"within [0.50, 1.00]")
        if self.family_min_confidence < self.min_confidence:
            raise ValueError(
                "AGENT_SEMANTIC_ROUTER_FAMILY_MIN_CONFIDENCE must be "
                ">= AGENT_SEMANTIC_ROUTER_MIN_CONFIDENCE")
        if float(self.timeout_seconds) <= 0:
            raise ValueError(
                "AGENT_SEMANTIC_ROUTER_HTTP_TIMEOUT_SECONDS must be "
                "positive")
        if int(self.max_input_chars) <= 0:
            raise ValueError(
                "AGENT_SEMANTIC_ROUTER_MAX_INPUT_CHARS must be positive")


def semantic_config_from_settings() -> SemanticRouterConfig:
    from retriva_gateway.config import settings
    config = SemanticRouterConfig(
        enabled=bool(settings.AGENT_SEMANTIC_ROUTER_ENABLED),
        min_confidence=float(
            settings.AGENT_SEMANTIC_ROUTER_MIN_CONFIDENCE),
        family_min_confidence=float(
            settings.AGENT_SEMANTIC_ROUTER_FAMILY_MIN_CONFIDENCE),
        timeout_seconds=float(
            settings.AGENT_SEMANTIC_ROUTER_HTTP_TIMEOUT_SECONDS),
        max_input_chars=int(
            settings.AGENT_SEMANTIC_ROUTER_MAX_INPUT_CHARS))
    config.validate()
    return config


@dataclass(frozen=True)
class SemanticHints:
    """Categorical, bounded router hints (never raw history)."""

    ambiguity_class: str
    workflow_family_hint: Optional[str] = None
    last_routed_data_plane: Optional[str] = None
    last_family: Optional[str] = None
    workflow_context_present: bool = False
    pending_confirmation_present: bool = False
    language: str = "en"


@dataclass(frozen=True)
class SemanticRoute:
    decision: str
    family: Optional[str]
    confidence: Optional[float]
    requires_clarification: bool
    failure_category: str = ""
    reason_codes: Tuple[str, ...] = ()


#: Informational intents eligible for the semantic router (Spec 040 §6).
_INFORMATIONAL = frozenset({
    Intent.RAG_QUESTION,
    Intent.WORKFLOW_DOCUMENTATION,
    Intent.STATUS_EXPLANATION,
    Intent.CAPABILITY_QUESTION,
})

_AMBIGUITY_REASON_SETS = (
    frozenset({ReasonCode.NO_DETERMINISTIC_MATCH,
               ReasonCode.NON_ADJACENT_AMBIGUITY}),
    # The workflow-adjacent ambiguity class is the incident class.  The
    # pipeline renders it as CLARIFICATION_REQUIRED; the raw engine
    # result is AMBIGUOUS, which is the router input (Spec 040 §6).
    frozenset({ReasonCode.NO_DETERMINISTIC_MATCH,
               ReasonCode.WORKFLOW_ADJACENT}),
)


def in_semantic_band(routed) -> bool:
    """Exact Phase C input band (Spec 040 §6)."""
    if routed is None:
        return False
    if getattr(routed, "claimed", None) is not None:
        return False
    if getattr(routed, "resolved", None) is not None:
        return False
    decision = routed.decision
    result = getattr(routed, "engine_result", None)
    if result is not None and result.intent is Intent.AMBIGUOUS:
        if frozenset(result.reason_codes) in _AMBIGUITY_REASON_SETS:
            return True
    if decision.explicitness is not Explicitness.IMPLICIT:
        return False
    return decision.intent in _INFORMATIONAL


def hints_for(routed, context_record=None, *, message: str = "") -> SemanticHints:
    """Build the ratified categorical hints from deterministic state."""
    decision = routed.decision
    result = getattr(routed, "engine_result", None)
    reasons = frozenset(
        result.reason_codes if result is not None
        else decision.reason_codes)
    if ReasonCode.NON_ADJACENT_AMBIGUITY in reasons:
        ambiguity = "NON_ADJACENT_AMBIGUITY"
    elif ReasonCode.WORKFLOW_ADJACENT in reasons:
        ambiguity = "WORKFLOW_ADJACENT"
    else:
        ambiguity = "INFORMATIONAL"
    topic = result.topic.value if result is not None else decision.topic.value
    family_hint = topic if topic in (
        "ACP", "QUALIFICATION", "COMPANY_IMPORT", "CAMPAIGN") else None
    record_family = None
    context_present = False
    pending = False
    if context_record is not None:
        context_present = True
        record_family = getattr(context_record, "family", None)
        pending = bool(getattr(context_record, "pending_confirmation", None))
    return SemanticHints(
        ambiguity_class=ambiguity,
        workflow_family_hint=family_hint,
        last_routed_data_plane=None,
        last_family=record_family,
        workflow_context_present=context_present,
        pending_confirmation_present=pending,
        language=_detect_language(message),
    )


def _detect_language(message: str) -> str:
    import re
    marker = re.compile(
        r"(?:come|cosa|quante|quanti|qual|perch|vorrei|posso|devo|"
        r"aziende|campagna|campagne)|\u00e0|\u00e8|\u00e9|\u00ec|\u00f2|"
        r"\u00f9", re.IGNORECASE)
    return "it" if marker.search(message or "") else "en"


def _card_payload(cards) -> list:
    payload = []
    for card in sorted(cards, key=lambda c: c.family):
        payload.append({
            "family": card.family,
            "read_only": bool(card.read_only),
            "tools": [
                {
                    "name": tool.name,
                    "description": (tool.description or "")[:300],
                    "destructive": bool(tool.destructive),
                }
                for tool in card.tools[:80]
            ],
        })
    return payload


def build_semantic_request(
        message: str, *, hints: SemanticHints, cards,
        correlation_id: str, config: SemanticRouterConfig) -> Dict[str, Any]:
    """Minimal privacy-safe v2 request: message + categorical hints +
    catalog cards + trace correlation only."""
    normalized = " ".join((message or "").split())
    return {
        "schema_version": "2",
        "prompt_id": "retriva-intent-classification",
        "prompt_version": "2",
        "message": normalized[:max(1, int(config.max_input_chars))],
        "language": hints.language,
        "ambiguity_class": hints.ambiguity_class,
        "workflow_family_hint": hints.workflow_family_hint,
        "last_routed_data_plane": hints.last_routed_data_plane,
        "last_family": hints.last_family,
        "workflow_context_present": bool(hints.workflow_context_present),
        "pending_confirmation_present":
            bool(hints.pending_confirmation_present),
        "capability_cards": _card_payload(cards),
        "purpose": "intent-classification",
        "correlation_id": (correlation_id or "")[:128],
    }


class SemanticRouter:
    """Structural protocol for a semantic-router transport."""

    async def classify(self, request: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class CoreEndpointSemanticRouter(SemanticRouter):
    """The single production transport: Core's internal v2 endpoint.

    Reuses the accepted ``CoreEndpointClassifier`` transport (same
    URL, dedicated service credential, purpose marker, correlation id,
    timeout, and no-recursion path).  The v2 request's
    ``prompt_version``/``schema_version`` select the v2 contract in
    Core.  No provider, model, endpoint, region, or credential field is
    request-selectable.
    """

    def __init__(self, *, service_auth_token: str = "",
                 timeout_seconds: float = 35.0) -> None:
        from retriva_gateway.core.routing.classifier import (
            CoreEndpointClassifier,
        )
        self._transport = CoreEndpointClassifier(
            service_auth_token=service_auth_token,
            timeout_seconds=timeout_seconds)

    async def classify(self, request: Dict[str, Any]) -> Dict[str, Any]:
        from retriva_gateway.core.routing.classifier import (
            ClassifierFailure,
            IntentClassificationError,
        )
        try:
            return await self._transport.classify(request)
        except IntentClassificationError as exc:
            mapping = {
                ClassifierFailure.INVALID_OUTPUT:
                    SemanticFailure.ROUTER_INVALID_OUTPUT,
                ClassifierFailure.CLASSIFIER_DISABLED:
                    SemanticFailure.ROUTER_UNAVAILABLE,
                ClassifierFailure.CLASSIFIER_UNAVAILABLE:
                    SemanticFailure.ROUTER_UNAVAILABLE,
            }
            raise SemanticRouterError(
                mapping.get(exc.category,
                            SemanticFailure.ROUTER_UNAVAILABLE)) \
                from None


def _fail(category: SemanticFailure) -> SemanticRoute:
    return SemanticRoute(
        decision="CLARIFY", family=None, confidence=None,
        requires_clarification=True, failure_category=category.value)


def validate_semantic_decision(
        payload: Any, *, cards) -> SemanticRouteDecisionV2:
    try:
        decision = SemanticRouteDecisionV2.model_validate(payload)
    except Exception:  # noqa: BLE001 — typed category only
        raise SemanticRouterError(
            SemanticFailure.ROUTER_INVALID_OUTPUT) from None
    if decision.schema_version != "2" or decision.prompt_version != "2":
        raise SemanticRouterError(
            SemanticFailure.ROUTER_SCHEMA_MISMATCH)
    families = {card.family for card in cards}
    if decision.decision.value == "FAMILY" \
            and decision.family.value not in families:
        raise SemanticRouterError(
            SemanticFailure.ROUTER_UNKNOWN_FAMILY)
    return decision


async def route_semantic(
        message: str, *, hints: SemanticHints, router: SemanticRouter,
        config: SemanticRouterConfig, correlation_id: str,
        cards: Optional[Tuple[CapabilityCard, ...]] = None,
        shadow: bool = True,
        route_served: str = "deterministic",
        ) -> SemanticRoute:
    """The ONE semantic-router call site (Spec 040 SC3).

    One call per band turn; no retries that re-invoke a model; all
    failures are typed and fail closed to CLARIFY.
    """
    if not config.enabled:
        routing_metrics().inc("router_bypass_total",
                              reason="router_disabled")
        return SemanticRoute(decision="CLARIFY", family=None,
                             confidence=None,
                             requires_clarification=True)
    if cards is None:
        cards = derive_cards()
    request = build_semantic_request(
        message, hints=hints, cards=cards,
        correlation_id=correlation_id, config=config)
    started = time.perf_counter()
    try:
        payload = await router.classify(request)
    except SemanticRouterError as exc:
        latency = time.perf_counter() - started
        routing_metrics().inc("router_failure_total",
                              category=exc.category.value)
        routing_metrics().observe_latency(latency)
        _record_shadow(correlation_id, "CLARIFY", None, None,
                       exc.category.value, latency, route_served,
                       shadow)
        return _fail(exc.category)
    except Exception:  # noqa: BLE001 — fail closed, no detail
        latency = time.perf_counter() - started
        routing_metrics().inc("router_failure_total",
                              category=SemanticFailure.
                              ROUTER_UNAVAILABLE.value)
        routing_metrics().observe_latency(latency)
        _record_shadow(correlation_id, "CLARIFY", None, None,
                       SemanticFailure.ROUTER_UNAVAILABLE.value,
                       latency, route_served, shadow)
        return _fail(SemanticFailure.ROUTER_UNAVAILABLE)
    latency = time.perf_counter() - started
    try:
        decision = validate_semantic_decision(payload, cards=cards)
    except SemanticRouterError as exc:
        routing_metrics().inc("router_failure_total",
                              category=exc.category.value)
        routing_metrics().observe_latency(latency)
        _record_shadow(correlation_id, "CLARIFY", None, None,
                       exc.category.value, latency, route_served,
                       shadow)
        return _fail(exc.category)

    routing_metrics().observe_latency(latency)
    confidence = float(decision.confidence)
    if decision.decision.value == "FAMILY":
        if confidence < config.family_min_confidence:
            routing_metrics().inc(
                "router_failure_total",
                category=SemanticFailure.ROUTER_BELOW_THRESHOLD.value)
            _record_shadow(correlation_id, "CLARIFY",
                           decision.family.value, confidence,
                           SemanticFailure.ROUTER_BELOW_THRESHOLD.value,
                           latency, route_served, shadow)
            return _fail(SemanticFailure.ROUTER_BELOW_THRESHOLD)
        routing_metrics().inc("router_decision_total", decision="FAMILY")
        _record_shadow(correlation_id, "FAMILY",
                       decision.family.value, confidence, "", latency,
                       route_served, shadow)
        return SemanticRoute(
            decision="FAMILY", family=decision.family.value,
            confidence=confidence, requires_clarification=False,
            reason_codes=tuple(r.value for r in decision.reason_codes))
    if decision.decision.value == "RAG":
        if confidence < config.min_confidence:
            routing_metrics().inc(
                "router_failure_total",
                category=SemanticFailure.ROUTER_BELOW_THRESHOLD.value)
            _record_shadow(correlation_id, "CLARIFY", None, confidence,
                           SemanticFailure.ROUTER_BELOW_THRESHOLD.value,
                           latency, route_served, shadow)
            return _fail(SemanticFailure.ROUTER_BELOW_THRESHOLD)
        routing_metrics().inc("router_decision_total", decision="RAG")
        _record_shadow(correlation_id, "RAG", None, confidence, "",
                       latency, route_served, shadow)
        return SemanticRoute(
            decision="RAG", family=None, confidence=confidence,
            requires_clarification=False,
            reason_codes=tuple(r.value for r in decision.reason_codes))
    routing_metrics().inc("router_decision_total", decision="CLARIFY")
    _record_shadow(correlation_id, "CLARIFY", None, confidence, "",
                   latency, route_served, shadow)
    return SemanticRoute(
        decision="CLARIFY", family=None, confidence=confidence,
        requires_clarification=True,
        reason_codes=tuple(r.value for r in decision.reason_codes))


# ---------------------------------------------------------------------------
# Shadow diagnostics (content-free; correlation ids only)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SemanticShadowRecord:
    correlation_id: str
    decision: str
    family: Optional[str]
    confidence: Optional[float]
    failure_category: str
    latency_s: float
    route_served: str
    timestamp: float


class SemanticShadowRing:
    def __init__(self, capacity: int = 256) -> None:
        self._lock = threading.Lock()
        self._records: Deque[SemanticShadowRecord] = deque(
            maxlen=capacity)

    def push(self, record: SemanticShadowRecord) -> None:
        with self._lock:
            self._records.append(record)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            records = list(self._records)
        return {
            "count": len(records),
            "records": [
                {
                    "correlation_id": r.correlation_id,
                    "decision": r.decision,
                    "family": r.family,
                    "confidence": r.confidence,
                    "failure_category": r.failure_category,
                    "latency_s": round(r.latency_s, 4),
                    "route_served": r.route_served,
                }
                for r in records
            ],
        }


_RING = SemanticShadowRing()
_RING_LOCK = threading.Lock()


def semantic_shadow_ring() -> SemanticShadowRing:
    return _RING


def reset_semantic_shadow_ring_for_tests() -> SemanticShadowRing:
    global _RING
    with _RING_LOCK:
        _RING = SemanticShadowRing()
    return _RING


def _record_shadow(correlation_id: str, decision: str,
                   family: Optional[str], confidence: Optional[float],
                   failure_category: str, latency: float,
                   route_served: str, shadow: bool = True) -> None:
    if not shadow:
        return
    semantic_shadow_ring().push(SemanticShadowRecord(
        correlation_id=correlation_id,
        decision=decision,
        family=family,
        confidence=confidence,
        failure_category=failure_category,
        latency_s=latency,
        route_served=route_served,
        timestamp=time.time(),
    ))
