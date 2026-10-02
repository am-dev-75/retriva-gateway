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

from retriva_gateway.config import settings
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
from .metrics import routing_metrics

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


def _emit_deterministic_metrics(result: "DeterministicResult",
                                 route: "Route", reasons: list) -> None:
    """Closed-label deterministic decision metrics (Spec 001 §Metrics).
    Off the classifier path; incremented for every deterministic route
    so the 11 families are exercised by the Gateway's own decisions."""
    m = routing_metrics()
    m.inc("deterministic_match_total", intent=result.intent.value)
    m.inc("routing_decision_total", route=route.value,
          source="deterministic")
    if route is Route.AGENT_LOOP and result.intent in _CONSEQUENTIAL_INTENTS:
        fam = (result.topic.value
               if result.topic.value in ("ACP", "QUALIFICATION",
                                          "COMPANY_IMPORT", "CAMPAIGN")
               else "unknown")
        m.inc("workflow_route_total", family=fam)
    elif route is Route.RAG:
        m.inc("rag_route_total")
    elif route is Route.CLARIFY:
        if ReasonCode.GUARD_RESOURCE_UNRESOLVED in reasons:
            m.inc("clarification_total", reason="guard_resource_unresolved")
        elif ReasonCode.MULTI_INTENT in reasons:
            m.inc("clarification_total", reason="multi_intent")
        elif ReasonCode.CONSEQUENTIAL_UNAVAILABLE in reasons:
            m.inc("clarification_total", reason="consequential_unavailable")
        elif ReasonCode.WORKFLOW_ADJACENT in reasons:
            m.inc("clarification_total", reason="workflow_adjacent")
        else:
            m.inc("clarification_total", reason="no_deterministic_match")
        # Explicit consequential intent deterministically rejected
        # (e.g. negated/hypothetical/quoted, or guard fail) is an
        # explicit-intent rejection for the closed operation label.
        if result.explicitness is Explicitness.EXPLICIT and \
                result.intent in _CONSEQUENTIAL_INTENTS:
            m.inc("explicit_intent_rejection_total",
                  operation=result.intent.value)


def _to_route(result: DeterministicResult) -> PhaseBChatRoute:
    reasons = list(result.reason_codes)

    if result.intent == Intent.UNSUPPORTED:
        # Typed refusal for unsupported workflows (R-UNSUPPORTED): the
        # decision keeps the UNSUPPORTED intent; the response is the
        # closed refusal template.
        out = _clarify(result, reasons, decision_intent=Intent.UNSUPPORTED)
        _emit_deterministic_metrics(result, out.route, reasons)
        return out

    if result.intent == Intent.CLARIFICATION_REQUIRED:
        # Multi-intent, unavailable vocabulary, or guard-fail clarification.
        out = _clarify(result, reasons)
        _emit_deterministic_metrics(result, out.route, reasons)
        return out

    if result.intent in _CONSEQUENTIAL_INTENTS:
        guard = evaluate_consequential_guard(result)
        if not guard.passed:
            reasons = list(dict.fromkeys(
                reasons + sorted(guard.reason_codes, key=lambda r: r.value)))
            out = _clarify(result, reasons)
            _emit_deterministic_metrics(result, out.route, reasons)
            return out
        out = _decision(result, Route.AGENT_LOOP, reasons)
        _emit_deterministic_metrics(result, out.route, reasons)
        return out

    if result.intent in (Intent.RAG_QUESTION, Intent.WORKFLOW_DOCUMENTATION,
                         Intent.STATUS_EXPLANATION,
                         Intent.CAPABILITY_QUESTION):
        out = _decision(result, Route.RAG, reasons)
        _emit_deterministic_metrics(result, out.route, reasons)
        return out

    if result.intent == Intent.AMBIGUOUS:
        if ReasonCode.NON_ADJACENT_AMBIGUITY in result.reason_codes:
            out = _decision(result, Route.RAG, reasons)
            _emit_deterministic_metrics(result, out.route, reasons)
            return out
        out = _clarify(result, reasons)
        _emit_deterministic_metrics(result, out.route, reasons)
        return out

    # Safe workflow proposal/analysis intents enter the bounded agent loop.
    out = _decision(result, Route.AGENT_LOOP, reasons)
    _emit_deterministic_metrics(result, out.route, reasons)
    return out


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


# ---------------------------------------------------------------------------
# Phase D/E — classifier policy (Spec 001 Phase D minimal integration
# superseded by the complete Phase E policy module: the decision tables,
# confidence semantics, shadow diagnostics, and the consequential
# prohibitions live in core/routing/policy.py).  Re-exported here for
# the established package surface; apply_classification dispatches to
# the shadow (route-neutral) or active (narrow authority) table.
# ---------------------------------------------------------------------------

from .policy import (  # noqa: E402,F401
    apply_active,
    apply_classification,
    apply_shadow,
)

_INFORMATIONAL = (Intent.RAG_QUESTION, Intent.WORKFLOW_DOCUMENTATION,
                   Intent.STATUS_EXPLANATION, Intent.CAPABILITY_QUESTION)


def classification_context_hints(registry, key) -> dict:
    """Privacy-safe categorical context summary (Spec 001 §Phase D/E):
    presence booleans and a closed family hint ONLY — never resource
    IDs, WorkflowContext fields, confirmation bindings, tenant/
    principal/session/KB identifiers, or any content."""
    try:
        record = registry.peek_context(key)
    except AttributeError:
        record = None
    if record is None:
        return {"workflow_context_present": False,
                "pending_confirmation_present": False,
                "workflow_family_hint": None}
    pending = record.pending_confirmation
    return {
        "workflow_context_present": True,
        "pending_confirmation_present": bool(
            pending is not None
            and pending.state is not None),
        "workflow_family_hint": record.family,
    }


def eligible_for_classification(routed: PhaseBChatRoute) -> bool:
    """Eligible deterministic ambiguity ONLY (Spec 001 Phase E — the
    complete accepted table): BOTH ambiguity classes the deterministic
    router cannot confidently classify —

    * workflow-adjacent: clarification whose closed reason set is
      exactly {NO_DETERMINISTIC_MATCH, WORKFLOW_ADJACENT};
    * non-adjacent: the RAG-routed AMBIGUOUS class whose reason set is
      exactly {NO_DETERMINISTIC_MATCH, NON_ADJACENT_AMBIGUITY}.

    Never eligible: deterministic informational/command outcomes,
    multi-intent clarify (MULTI_INTENT), unavailable-vocabulary clarify
    (CONSEQUENTIAL_UNAVAILABLE), guard-fail clarify
    (GUARD_RESOURCE_UNRESOLVED), Phase C follow-up shapes
    (FOLLOWUP_CONTEXT — registry paths own them), bare-affirmation
    claim candidates, and every deterministic veto (negated/
    hypothetical/quoted/code/prompt-writing — the explicitness veto
    carries them)."""
    decision = routed.decision
    # Defense-in-depth (E-D1): no recognized consequential operation or
    # consequential candidate may ever become classifier-eligible.  The
    # deterministic engine and guard pipeline are authoritative; the
    # classifier never routes consequential intent (the final
    # defense-in-depth assertion at the call site mirrors this).
    if decision.intent in _CONSEQUENTIAL_INTENTS:
        return False
    if ReasonCode.CONSEQUENTIAL_CANDIDATE in decision.reason_codes:
        return False
    if (routed.claimed is not None
            or routed.resolved is not None):
        return False
    if decision.explicitness in (Explicitness.NEGATED,
                                  Explicitness.HYPOTHETICAL,
                                  Explicitness.QUOTED_EXAMPLE):
        return False
    reasons = set(decision.reason_codes)
    if decision.intent is Intent.AMBIGUOUS:
        return reasons == {ReasonCode.NO_DETERMINISTIC_MATCH,
                           ReasonCode.NON_ADJACENT_AMBIGUITY}
    if decision.intent is Intent.CLARIFICATION_REQUIRED:
        return reasons == {ReasonCode.NO_DETERMINISTIC_MATCH,
                           ReasonCode.WORKFLOW_ADJACENT}
    return False


def is_consequential_candidate(routed: "PhaseBChatRoute") -> bool:
    """Final defense-in-depth check at the single classifier call site
    (E-D1 invariant): a recognized consequential operation or a
    consequential candidate must never reach the classifier."""
    decision = routed.decision
    if decision.intent in _CONSEQUENTIAL_INTENTS:
        return True
    reasons = set(decision.reason_codes)
    if ReasonCode.CONSEQUENTIAL_CANDIDATE in reasons:
        return True
    # A consequential operation whose explicit resource failed the guard
    # (no opaque identifier / unresolved) clarifies deterministically and
    # must never reach the classifier (E-D1: the guard-fail path also
    # closes the consequential route).
    if (decision.intent is Intent.CLARIFICATION_REQUIRED
            and ReasonCode.GUARD_RESOURCE_UNRESOLVED in reasons
            and decision.explicitness is Explicitness.EXPLICIT):
        return True
    return False


def classifier_bypass_reason(routed: "PhaseBChatRoute") -> str:
    """Highest-precedence closed bypass reason for a turn in which the
    classifier is NOT invoked (E-D2).  Exactly one reason per turn."""
    decision = routed.decision
    reasons = set(decision.reason_codes)
    if routed.claimed is not None:
        return "confirmation_path"
    if routed.resolved is not None:
        return "guard_terminal"
    if ReasonCode.MULTI_INTENT in reasons:
        return "multi_intent"
    if decision.intent in _CONSEQUENTIAL_INTENTS:
        # Resolved consequential resource -> guard PASS (agent loop);
        # unresolved -> consequential candidate (guard fail).  Both are
        # deterministic, never classifier-driven.
        if routed.route is Route.AGENT_LOOP:
            return "guard_terminal"
        return "consequential_candidate"
    if ReasonCode.CONSEQUENTIAL_CANDIDATE in reasons:
        return "consequential_candidate"
    # A consequential operation whose explicit resource failed the guard
    # (no opaque identifier / unresolved) closes deterministically as a
    # consequential candidate (E-D1/E-D2).
    if (decision.intent is Intent.CLARIFICATION_REQUIRED
            and ReasonCode.GUARD_RESOURCE_UNRESOLVED in reasons
            and decision.explicitness is Explicitness.EXPLICIT):
        return "consequential_candidate"
    return "deterministic_terminal"


# ---------------------------------------------------------------------------
# Phase E — streaming gate (Spec 001 §Streaming policy; C5/7b).  The
# deterministic engine ONLY: no classifier, no registry access, no
# tools, no agent loop, no mutation — evaluated BEFORE any classifier
# eligibility, in shadow/active only (mode off bypasses the gate and
# preserves legacy streaming exactly).
# ---------------------------------------------------------------------------

class StreamingDecision:
    """Closed streaming-gate outcomes."""

    RAG_PASSTHROUGH = "rag_passthrough"
    REFUSE_STREAM = "refuse_stream"
    STREAM_CLARIFY = "stream_clarify"


#: The closed workflow-intent set for the streaming refusal (C5):
#: mutation or safe proposal intents (explicitness EXPLICIT).
_STREAM_WORKFLOW_INTENTS = frozenset({
    Intent.ACP_COHORT_PROPOSAL, Intent.ACP_COHORT_REVIEW,
    Intent.ACP_COHORT_APPROVAL, Intent.ACP_GENERATION,
    Intent.ACP_REVIEW, Intent.ACP_APPROVAL, Intent.ACP_ACTIVATION,
    Intent.ACP_SUPERSESSION, Intent.ACP_ROLLBACK,
    Intent.ACP_EVIDENCE_ENRICHMENT,
    Intent.ACP_EVIDENCE_ENRICHMENT_STATUS,
    Intent.ACP_EVIDENCE_ACCEPTANCE,
    Intent.QUALIFICATION_REQUEST, Intent.QUALIFICATION_REVIEW,
    Intent.QUALIFICATION_APPROVAL,
    Intent.COMPANY_IMPORT_ANALYSIS, Intent.COMPANY_IMPORT_REVIEW,
    Intent.COMPANY_IMPORT_APPROVAL, Intent.COMPANY_IMPORT_COMMIT,
    Intent.CAMPAIGN_CREATE, Intent.CAMPAIGN_AUDIENCE_ANALYSIS,
    Intent.CAMPAIGN_AUDIENCE_REVIEW, Intent.CAMPAIGN_AUDIENCE_APPROVAL,
    Intent.CAMPAIGN_AUDIENCE_COMMIT, Intent.CAMPAIGN_HISTORY_IMPORT,
    Intent.CAMPAIGN_MARK_ADDRESSED, Intent.CAMPAIGN_OUTCOME_UPDATE,
})


def classify_streaming_message(message: str):
    """The deterministic streaming classification (engine only).

    Returns (StreamingDecision, workflow_family or None, reason):
    * RAG_PASSTHROUGH — clear informational, non-adjacent ambiguity,
      and every non-workflow shape: the unchanged cited SSE RAG path;
    * REFUSE_STREAM — an explicit supported workflow command: the
      typed 409 (never SSE start, never a tool);
    * STREAM_CLARIFY — workflow-adjacent ambiguity (incl. multi-intent,
      guard-fail, unavailable-vocabulary, and follow-up shapes): the
      neutral streamed clarification (no classifier call, no
      retrieval, no tools, execute nothing).
    """
    result = _ENGINE.classify(message)
    decision = RoutingDecision(
        route=Route.RAG,
        source=DecisionSource.DETERMINISTIC,
        topic=result.topic,
        intent=result.intent,
        mode=result.mode,
        explicitness=result.explicitness,
        reason_codes=result.reason_codes)
    if (result.intent in _STREAM_WORKFLOW_INTENTS
            and result.explicitness is Explicitness.EXPLICIT):
        # Typed 409 only when the deterministic workflow family is
        # sufficiently known from the message itself (a recognized family
        # noun or an explicit resource); a family merely implied by the
        # verb is NOT sufficient (E-D1: an unresolved consequential
        # command must not claim a family it does not actually have).
        # Otherwise the neutral streamed clarification applies.
        fams = {t for t in result.families
                if t.value in ("ACP", "QUALIFICATION", "COMPANY_IMPORT",
                               "CAMPAIGN")}
        if fams:
            family = sorted(fams, key=lambda t: t.value)[0].value
            return StreamingDecision.REFUSE_STREAM, family, result
        return StreamingDecision.STREAM_CLARIFY, None, result
    reasons = set(result.reason_codes)
    if result.intent in (Intent.AMBIGUOUS,
                        Intent.CLARIFICATION_REQUIRED):
        adjacent = bool(reasons & {
            ReasonCode.WORKFLOW_ADJACENT, ReasonCode.MULTI_INTENT,
            ReasonCode.GUARD_RESOURCE_UNRESOLVED,
            ReasonCode.CONSEQUENTIAL_UNAVAILABLE,
            ReasonCode.FOLLOWUP_CONTEXT,
            ReasonCode.CONSEQUENTIAL_CANDIDATE})
        if adjacent:
            return StreamingDecision.STREAM_CLARIFY, None, result
    return StreamingDecision.RAG_PASSTHROUGH, None, result
