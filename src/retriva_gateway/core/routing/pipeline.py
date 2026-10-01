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

"""Phase B routing adapter — a TEMPORARY, bounded integration shim.

This is NOT the Phase E complete decision policy
(``core/routing/policy.py``, authorized separately in Phase E).  It
contains only the Phase B deterministic orchestration needed to wire the
accepted deterministic subset into the chat path:

    deterministic engine -> explicit-intent guard scaffold -> route

Route mapping (accepted decision table, deterministic subset only):

- clear informational / documentation / capability / status, negated,
  hypothetical, quoted, prompt-writing  -> RAG (plain chat);
- clear safe workflow proposal/analysis                  -> AGENT_LOOP;
- explicit consequential + guard scaffold PASS           -> AGENT_LOOP;
- explicit consequential + guard scaffold FAIL           -> CLARIFY;
- vocabulary without a C1 intent (import rejection,
  deactivation)                                          -> CLARIFY;
- MULTI-INTENT                                           -> CLARIFY;
- AMBIGUOUS workflow-adjacent                            -> CLARIFY;
- AMBIGUOUS non-adjacent                                 -> RAG.

Phase boundaries (documented, fail-closed): no classifier exists until
Phase D, so ``shadow`` and ``active`` behave identically here — the
deterministic subset — and ``active`` grants no classifier influence; the
classifier-unavailable fallback of the accepted decision table is
therefore the permanent Phase B behavior.  Streaming is NOT handled here
(Phase E); ``chat.py`` keeps the legacy streaming path in every mode.
"""

from dataclasses import dataclass
from typing import Optional

from .clarifications import build_clarification
from .deterministic import DeterministicEngine, DeterministicResult
from .guards import (
    CONSEQUENTIAL_INTENTS as _CONSEQUENTIAL_INTENTS,
    evaluate_consequential_guard,
)
from .taxonomy import (
    DecisionSource,
    Intent,
    InteractionMode,
    ReasonCode,
    Route,
    RoutingDecision,
)

_ENGINE = DeterministicEngine()


@dataclass(frozen=True)
class PhaseBChatRoute:
    """Non-streaming route outcome for one chat turn (Phase B subset)."""

    route: Route
    decision: RoutingDecision
    clarification: Optional[str] = None


def route_non_streaming(message: str) -> PhaseBChatRoute:
    """Deterministic Phase B routing for one non-streaming message."""
    result = _ENGINE.classify(message)
    return _to_route(result)


def _to_route(result: DeterministicResult) -> PhaseBChatRoute:
    reasons = list(result.reason_codes)

    if result.intent == Intent.UNSUPPORTED:
        # Typed refusal for unsupported workflows (R-UNSUPPORTED): the
        # decision keeps the UNSUPPORTED intent; the response is the
        # closed refusal template.
        return _clarify(result, reasons, decision_intent=Intent.UNSUPPORTED)

    if result.intent == Intent.CLARIFICATION_REQUIRED:
        # Multi-intent, unavailable vocabulary, or guard-fail clarification.
        return _clarify(result, reasons)

    if result.intent in _CONSEQUENTIAL_INTENTS:
        guard = evaluate_consequential_guard(result)
        if not guard.passed:
            reasons = list(dict.fromkeys(
                reasons + sorted(guard.reason_codes, key=lambda r: r.value)))
            return _clarify(result, reasons)
        return _decision(result, Route.AGENT_LOOP, reasons)

    if result.intent in (Intent.RAG_QUESTION, Intent.WORKFLOW_DOCUMENTATION,
                         Intent.STATUS_EXPLANATION,
                         Intent.CAPABILITY_QUESTION):
        return _decision(result, Route.RAG, reasons)

    if result.intent == Intent.AMBIGUOUS:
        if ReasonCode.NON_ADJACENT_AMBIGUITY in result.reason_codes:
            return _decision(result, Route.RAG, reasons)
        return _clarify(result, reasons)

    # Safe workflow proposal/analysis intents enter the bounded agent loop.
    return _decision(result, Route.AGENT_LOOP, reasons)


def _decision(result: DeterministicResult, route: Route,
              reasons: list) -> PhaseBChatRoute:
    decision = RoutingDecision(
        route=route,
        source=DecisionSource.DETERMINISTIC,
        topic=result.topic,
        intent=result.intent,
        mode=result.mode,
        explicitness=result.explicitness,
        confidence=None,
        reason_codes=reasons,
        classifier_invoked=False,
        shadow=False,
    )
    return PhaseBChatRoute(route=route, decision=decision)


def _clarify(result: DeterministicResult, reasons: list,
             decision_intent: Intent = Intent.CLARIFICATION_REQUIRED
             ) -> PhaseBChatRoute:
    guard_failed = ReasonCode.GUARD_RESOURCE_UNRESOLVED in reasons
    decision = RoutingDecision(
        route=Route.CLARIFY,
        source=(DecisionSource.GUARD if guard_failed
                else DecisionSource.DETERMINISTIC),
        topic=result.topic,
        intent=decision_intent,
        mode=InteractionMode.UNKNOWN,
        explicitness=result.explicitness,
        confidence=None,
        reason_codes=reasons or [ReasonCode.NO_DETERMINISTIC_MATCH],
        classifier_invoked=False,
        shadow=False,
    )
    return PhaseBChatRoute(
        route=Route.CLARIFY, decision=decision,
        clarification=build_clarification(result, tuple(reasons)))
