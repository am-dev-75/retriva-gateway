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
from .context import (
    BARE_AFFIRMATIVE_AMBIGUOUS,
    BARE_AFFIRMATIVE_NO_CONFIRMATION,
    CLAIM_EXPIRED,
    ClaimResult,
    ClaimRejection,
    ClaimedConfirmationContext,
    ResolvedReference,
    WorkflowContextKey,
    WorkflowContextRegistry,
)
from .deterministic import (
    DeterministicEngine,
    DeterministicResult,
    is_bare_affirmative_message,
)
from .guards import (
    CONSEQUENTIAL_INTENTS as _CONSEQUENTIAL_INTENTS,
    evaluate_consequential_guard,
)
from .taxonomy import (
    DecisionSource,
    Explicitness,
    Intent,
    InteractionMode,
    ReasonCode,
    Route,
    RoutingDecision,
    Topic,
)

_ENGINE = DeterministicEngine()


@dataclass(frozen=True)
class TrustedRoutingContext:
    """Trusted Phase C routing inputs (server-side only).

    key fields from the trusted request context; principal from the
    authenticated Gateway principal.  Never message content, model
    output, tool arguments, custom metadata, classifier output, or
    untrusted headers.
    """

    registry: WorkflowContextRegistry
    key: WorkflowContextKey
    principal_id: str


@dataclass(frozen=True)
class PhaseBChatRoute:
    """Non-streaming route outcome for one chat turn (Phase B subset).

    Phase C additions: ``claimed`` (the immutable server-only claimed
    execution context after a successful atomic confirmation claim) and
    ``resolved`` (an ordinary-context resource resolution for an
    explicit follow-up).  Both default to None; the no-context path is
    bit-identical to Phase B/C0.
    """

    route: Route
    decision: RoutingDecision
    clarification: Optional[str] = None
    claimed: Optional[ClaimedConfirmationContext] = None
    resolved: Optional[ResolvedReference] = None


def route_non_streaming(message: str,
                         *,
                         routing: Optional[TrustedRoutingContext] = None,
                         ) -> PhaseBChatRoute:
    """Deterministic routing for one non-streaming message.

    Without ``routing`` this is the Phase B/C0 behavior, unchanged.
    With ``routing`` (mode shadow/active only) the Phase C registry
    participates: bare affirmatives may claim exactly one eligible
    typed pending confirmation; explicit-verb follow-ups may resolve an
    ordinary resource reference; explicit commands arm ordinary context
    (routing hints only).  Multi-intent messages never touch the
    registry (clarify, execute nothing, write nothing).
    """
    result = _ENGINE.classify(message)
    routed = _to_route(result)
    if routing is None:
        return routed
    return _phase_c(routed, result, message, routing)


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


# ---------------------------------------------------------------------------
# Phase C — typed workflow-context participation (Spec 001 Phase C).
# ---------------------------------------------------------------------------

def _phase_c(routed: PhaseBChatRoute, result: DeterministicResult,
             message: str, routing: TrustedRoutingContext
             ) -> PhaseBChatRoute:
    """Registry-aware routing.  Every path fails closed; the registry
    is routing state/evidence only and authorizes nothing (the domain
    repeats every validation)."""
    # Multi-intent policy B: clarify, execute nothing, create no
    # WorkflowContext, create/claim no PendingConfirmation.  The
    # registry is not touched.
    if (result.intent == Intent.CLARIFICATION_REQUIRED
            and ReasonCode.MULTI_INTENT in result.reason_codes):
        return routed

    registry = routing.registry
    key = routing.key

    # Bare affirmative (closed set; carries no operation verb and no
    # resource): may enter a consequential workflow ONLY through an
    # atomic claim of exactly one eligible PENDING confirmation.
    if (result.rule == "R-DEFAULT"
            and result.intent is Intent.AMBIGUOUS
            and ReasonCode.NO_DETERMINISTIC_MATCH
            in result.reason_codes
            and is_bare_affirmative_message(message)):
        claim = registry.claim(key, routing.principal_id)
        return _claim_route(claim)

    # Explicit follow-up (consequential verb, EXPLICIT, but no opaque
    # resource in the message): resolve from ordinary WorkflowContext
    # when the family matches and allowed-next hints permit the
    # operation.  Ordinary context assists resource resolution only;
    # it supplies no authorization.
    if (routed.route is Route.CLARIFY
            and result.intent in _CONSEQUENTIAL_INTENTS
            and result.explicitness is Explicitness.EXPLICIT
            and ReasonCode.GUARD_RESOURCE_UNRESOLVED
            in routed.decision.reason_codes):
        resolved = registry.resolve_follow_up(
            key, result.topic.value, result.intent.value)
        if resolved is not None:
            guard = evaluate_consequential_guard(
                result, resolved_resource=resolved.resource_id)
            if guard.passed:
                decision = RoutingDecision(
                    route=Route.AGENT_LOOP,
                    source=DecisionSource.GUARD,
                    topic=result.topic,
                    intent=result.intent,
                    mode=result.mode,
                    explicitness=result.explicitness,
                    confidence=None,
                    reason_codes=[ReasonCode.FOLLOWUP_CONTEXT],
                    classifier_invoked=False,
                    shadow=False)
                return PhaseBChatRoute(
                    route=Route.AGENT_LOOP, decision=decision,
                    resolved=resolved)
        return routed

    # Weak follow-up shape (pronoun / generic-resource object: the
    # engine detected consequential operation verbs — R-DEFAULT with
    # FOLLOWUP_CONTEXT — but no resource).  Phase C resolves the
    # resource from ordinary WorkflowContext under the same conditions
    # (family match where the message carries one, allowed-next hints,
    # exactly one record, no pending-confirmation conflict); the
    # record's allowed-next hints arbitrate the candidate operations in
    # closed deterministic order.  Ambiguity or no hit keeps the
    # fail-closed clarification.
    if (routed.route in (Route.CLARIFY, Route.RAG)
            and result.rule == "R-DEFAULT"
            and result.intent is Intent.AMBIGUOUS
            and ReasonCode.FOLLOWUP_CONTEXT in result.reason_codes
            and any(intent in _CONSEQUENTIAL_INTENTS
                    for intent in result.followup_intents)):
        family_signal = (result.topic.value
                         if result.topic is not Topic.GENERAL else None)
        for candidate in result.followup_intents:
            if candidate not in _CONSEQUENTIAL_INTENTS:
                continue
            resolved = registry.resolve_follow_up(
                key, family_signal, candidate.value)
            if resolved is not None:
                decision = RoutingDecision(
                    route=Route.AGENT_LOOP,
                    source=DecisionSource.GUARD,
                    topic=Topic(result.topic.value),
                    intent=candidate,
                    mode=InteractionMode.DESTRUCTIVE_MUTATION
                    if candidate in _CONSEQUENTIAL_INTENTS
                    else InteractionMode.ANALYSIS,
                    explicitness=Explicitness.EXPLICIT,
                    confidence=None,
                    reason_codes=[ReasonCode.FOLLOWUP_CONTEXT],
                    classifier_invoked=False,
                    shadow=False)
                return PhaseBChatRoute(
                    route=Route.AGENT_LOOP, decision=decision,
                    resolved=resolved)
        return routed

    # Explicit command that enters the agent loop with an opaque
    # resource: arm/replace ORDINARY context (routing hints only —
    # never a confirmation; the deterministic adapter may create or
    # replace ordinary WorkflowContext only).
    if (routed.route is Route.AGENT_LOOP
            and result.resource_reference):
        from .context import resource_type_for
        registry.observe_command(
            key, result.topic.value,
            resource_type_for(result.resource_reference),
            result.resource_reference, result.intent.value)
    return routed


def _claim_route(claim: ClaimResult) -> PhaseBChatRoute:
    """Route a bare affirmative by its atomic claim outcome."""
    if claim.succeeded:
        claimed = claim.claimed
        decision = RoutingDecision(
            route=Route.AGENT_LOOP,
            source=DecisionSource.GUARD,
            topic=Topic.ACP,
            intent=Intent.ACP_ACTIVATION,
            mode=InteractionMode.DESTRUCTIVE_MUTATION,
            explicitness=Explicitness.EXPLICIT,
            confidence=None,
            reason_codes=[ReasonCode.FOLLOWUP_CONTEXT],
            classifier_invoked=False,
            shadow=False)
        return PhaseBChatRoute(
            route=Route.AGENT_LOOP, decision=decision, claimed=claimed)
    if claim.rejection is ClaimRejection.EXPIRED:
        return _claim_clarification(
            CLAIM_EXPIRED, ReasonCode.NO_DETERMINISTIC_MATCH)
    if claim.rejection is ClaimRejection.AMBIGUOUS:
        return _claim_clarification(
            BARE_AFFIRMATIVE_AMBIGUOUS, ReasonCode.MULTI_INTENT)
    # NO_CONFIRMATION / PRINCIPAL_MISMATCH / KEY_MISMATCH /
    # STATE_MISMATCH: fail closed to clarification; execute nothing.
    return _claim_clarification(
        BARE_AFFIRMATIVE_NO_CONFIRMATION,
        ReasonCode.NO_DETERMINISTIC_MATCH)


def _claim_clarification(text: str, reason: ReasonCode
                         ) -> PhaseBChatRoute:
    decision = RoutingDecision(
        route=Route.CLARIFY,
        source=DecisionSource.GUARD,
        topic=Topic.ACP,
        intent=Intent.CLARIFICATION_REQUIRED,
        mode=InteractionMode.UNKNOWN,
        explicitness=Explicitness.AMBIGUOUS,
        confidence=None,
        reason_codes=[reason],
        classifier_invoked=False,
        shadow=False)
    return PhaseBChatRoute(
        route=Route.CLARIFY, decision=decision, clarification=text)
