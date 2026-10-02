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

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse
from retriva_gateway.core.client import core_client
from retriva_gateway.core.filters import FilterManager
from loguru import logger
from typing import Any, Dict, List, Optional
import datetime
import json

from retriva_gateway.core.models import ChatRequest
from retriva_gateway.core.context import get_correlation_id
from retriva_gateway.config import settings
from retriva_gateway.core.routing.metrics import routing_metrics

router = APIRouter(tags=["chat"])


def _run_agent_mode(request: ChatRequest, corr_id: str) -> Optional[JSONResponse]:
    """Decide whether this request should run the tool-calling agent loop.

    Agent mode runs when: tools are enabled in config, the request is
    non-streaming, and EITHER the client explicitly opted in
    (``tools_enabled`` + ``session_id`` — the qualification/import
    surfaces) OR the message matches a deterministic CRM-workflow
    intent (company-intelligence workflows cannot be answered by the
    knowledge-base pipeline; routing them to plain RAG produces the
    generic grounding refusal).  Routing is intent detection only —
    never authorization; the tools and the trusted principal decide
    what may run.

    Spec 001 / ADR-0002 (Phase B): ``AGENT_INTENT_ROUTER_MODE`` selects
    the router.  ``off`` (default, rollback state) keeps the legacy
    single-regex path below with exact legacy behavior, including the
    documented D1-D5 defects.  ``shadow``/``active`` route non-streaming
    messages through the new deterministic pipeline (Phase B subset: no
    classifier until Phase D).  Streaming is NOT handled by the new
    pipeline in Phase B — it keeps the legacy passthrough in every mode
    (the typed 409 arrives in Phase E).
    """
    if not settings.AGENT_TOOLS_ENABLED:
        return None
    if request.tools_enabled and request.session_id:
        if request.stream:
            # Agent mode is non-streaming in v1; fall back to plain chat.
            logger.warning(f"[{corr_id}] agent mode requested with stream=True; using plain chat")
            return None
        return _AGENT_SENTINEL
    if request.stream:
        # Spec 001 §Streaming policy (Phase E): mode off bypasses this
        # gate and preserves legacy streaming EXACTLY.  In shadow and
        # active the gate uses the deterministic engine ONLY — never
        # the classifier, never the registry, never the agent loop,
        # never a tool; it never claims a mutation occurred.
        if settings.AGENT_INTENT_ROUTER_MODE == "off":
            return None
        from retriva_gateway.core.routing.pipeline import (
            StreamingDecision,
            classify_streaming_message,
        )
        decision, family, engine_result = classify_streaming_message(
            request.message or "")
        if decision is StreamingDecision.REFUSE_STREAM:
            # 7.2: deterministic workflow command over streaming —
            # typed 409, no SSE start, no tool, no execution claim.
            routing_metrics().inc(
                "routing_decision_total", route="REFUSE_STREAM",
                source="deterministic")
            return _streaming_refusal(family, corr_id)
        if decision is StreamingDecision.STREAM_CLARIFY:
            # 7.3: workflow-adjacent ambiguity — neutral streamed
            # clarification (no classifier call, no retrieval, no
            # tools); the classifier is structurally bypassed here.
            routing_metrics().inc(
                "classifier_bypass_total", reason="streaming")
            routing_metrics().inc(
                "routing_decision_total", route="STREAM_CLARIFY",
                source="deterministic")
            return _streaming_clarification(corr_id, engine_result)
        # 7.1 / non-adjacent ambiguity: the unchanged cited SSE RAG
        # passthrough below.
        return None
    if settings.AGENT_INTENT_ROUTER_MODE == "off":
        # Legacy router — authoritative path in off (Spec 001 §Activation
        # model); do not reimplement legacy behavior in the new engine.
        from retriva_gateway.core.intent import IntentDetector
        if IntentDetector.is_crm_workflow(
                request.message or "",
                session_key=request.session_id):
            logger.info(
                f"[{corr_id}] Chat routing: CRM workflow intent → "
                f"agent loop")
            return _AGENT_SENTINEL
        return None
    # New deterministic pipeline (shadow/active; Phase B subset +
    # Phase C typed workflow-context participation).
    from retriva_gateway.core.context import get_principal
    from retriva_gateway.core.routing import (
        TrustedRoutingContext,
        classifier_bypass_reason,
        eligible_for_classification,
        get_workflow_context_registry,
        route_non_streaming,
    )
    from retriva_gateway.core.routing.context import WorkflowContextKey
    key = WorkflowContextKey(
        tenant_id=settings.DEFAULT_TENANT_ID,
        session_id=request.session_id or f"sess_{corr_id}",
        kb_id=request.kb_ids[0] if request.kb_ids else "default")
    routing = TrustedRoutingContext(
        registry=get_workflow_context_registry(),
        key=key,
        principal_id=get_principal().id)
    routed = route_non_streaming(request.message or "", routing=routing)
    decision = routed.decision
    # Phase D (Spec 001): eligible deterministic ambiguity only, and
    # only when the (advisory, untrusted) classifier is enabled.  The
    # SINGLE authorized call site lives in the endpoint's
    # _resolve_classification (this function stays synchronous); the
    # deterministic result stands unchanged on any classifier failure.
    if (settings.AGENT_INTENT_CLASSIFIER_ENABLED
            and eligible_for_classification(routed)):
        return _ClassifierEligible(
            routed=routed, message=request.message or "", key=key)
    # The classifier is NOT invoked for this turn: the deterministic
    # engine/guard pipeline is authoritative and the message is outside
    # the accepted eligibility window.  Record exactly one highest-
    # precedence closed bypass reason (E-D2).  Mode off never reaches
    # this path (the legacy router above returns first), so the mode_off
    # reason stays reserved for the mode-off invariant and is not emitted
    # here.
    if not settings.AGENT_INTENT_CLASSIFIER_ENABLED:
        routing_metrics().inc(
            "classifier_bypass_total", reason="classifier_disabled")
    else:
        routing_metrics().inc(
            "classifier_bypass_total",
            reason=classifier_bypass_reason(routed))
    if routed.route.value == "AGENT_LOOP":
        logger.info(
            f"[{corr_id}] Chat routing: deterministic pipeline → agent "
            f"loop (intent={decision.intent.value}, "
            f"reasons={[r.value for r in decision.reason_codes]})")
        if routed.claimed is not None or routed.resolved is not None:
            # Phase C: carry the server-only claimed execution context /
            # ordinary resolved reference into the loop admission.
            return _AgentAdmission(
                claimed=routed.claimed, resolved=routed.resolved)
        return _AGENT_SENTINEL
    if routed.route.value == "CLARIFY":
        logger.info(
            f"[{corr_id}] Chat routing: deterministic pipeline → "
            f"clarification (intent={decision.intent.value}, "
            f"reasons={[r.value for r in decision.reason_codes]})")
        return JSONResponse(content={
            "id": f"msg_{datetime.datetime.now().timestamp()}",
            "role": "assistant",
            "content": routed.clarification,
            "timestamp": datetime.datetime.now().isoformat(),
            "citations": [],
        })
    return None


# Sentinel returned by _run_agent_mode when the agent path should run.
_AGENT_SENTINEL = object()


class _AgentAdmission:
    """Phase C agent-loop admission carrying server-only routing
    context (a claimed execution context or an ordinary resolved
    reference) into the bounded loop.  Never model-visible, never
    request-body-settable; constructed only by ``_run_agent_mode``."""

    def __init__(self, *, claimed=None, resolved=None):
        self.claimed = claimed
        self.resolved = resolved


class _ClassifierEligible:
    """Phase D internal marker: an eligible deterministic ambiguity the
    (untrusted, advisory) classifier may be consulted for.  Returned
    only when the classifier is ENABLED and mode is shadow/active (the
    legacy/off path never constructs it); the async endpoint resolves
    it through the SINGLE authorized call site."""

    def __init__(self, *, routed, message, key):
        self.routed = routed
        self.message = message
        self.key = key


#: The retry contract's closed endpoint reference (the Gateway's own
#: chat route; Spec 001 C5 — machine-readable, content-free).
_CHAT_ENDPOINT_PATH = "/api/v2/chat"

#: Closed reason code for the streaming refusal (C5: safe reason).
_STREAM_REFUSAL_REASON = "streaming_workflow_command"


def _streaming_refusal(family, corr_id: str) -> JSONResponse:
    """7.2 (Spec 001 C5): the typed 409 with the machine-readable
    retry contract.  No SSE starts; no tool; the Gateway performs no
    automatic retry; the body never contains the raw message, tool
    arguments, model output, confirmation data, resource IDs, tenant or
    principal identity, or internal details."""
    detail = {
        "code": "workflow_stream_unsupported",
        "message": (
            "Workflow operations require a non-streaming request. "
            "Resend the same request without streaming to run the "
            "operation."),
        "retry": {
            "mode": "non_streaming",
            "action": "resend_without_stream",
            "endpoint": _CHAT_ENDPOINT_PATH,
        },
        "correlation_id": corr_id,
        "reason": _STREAM_REFUSAL_REASON,
    }
    # workflow_family only when safely known deterministically.
    if family:
        detail["workflow_family"] = family
    return JSONResponse(status_code=409, content={"detail": detail})


def _streaming_clarification(corr_id: str, result):
    """7.3 (Spec 001): the neutral streamed clarification — SSE opens,
    emits the deterministic clarification text, closes.  No classifier
    call, no retrieval, no tools, no execution; no new SSE event types
    (the established `data: {chunk}` shape)."""
    from fastapi.responses import StreamingResponse
    from retriva_gateway.core.routing.clarifications import (
        build_clarification,
    )

    text = build_clarification(result)

    async def _generator():
        first = {"id": f"chatcmpl-clarify-{corr_id}",
                 "object": "chat.completion.chunk",
                 "choices": [{"index": 0,
                              "delta": {"role": "assistant"}}]}
        yield f"data: {json.dumps(first)}\n\n".encode("utf-8")
        body = {"id": f"chatcmpl-clarify-{corr_id}",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0,
                             "delta": {"content": text}}]}
        yield f"data: {json.dumps(body)}\n\n".encode("utf-8")
        done = {"id": f"chatcmpl-clarify-{corr_id}",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}}]}
        yield f"data: {json.dumps(done)}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
    return StreamingResponse(_generator(), media_type="text/event-stream")


async def _resolve_classification(eligible, corr_id):
    """Spec 001 §Phase E — the SINGLE authorized classifier call site.

    Builds the minimal privacy-safe request (current normalized
    truncated message + categorical presence hints + prompt identity +
    trace correlation ONLY), calls the dedicated Core endpoint adapter,
    strictly re-validates the untrusted C2 response, times the call, and
    applies the accepted deterministic policy (pipeline.apply_
    classification).  On ANY failure the deterministic routed result
    stands (fail_mode=clarify): shadow records the failure for the
    diagnostic ring; active applies only the narrow prerequisites.
    Recursion is impossible: this flow never touches chat, RAG, the
    agent loop, tools, the reranker, or another routing pass.
    """
    import time as _time

    from retriva_gateway.core.routing.classifier import (
        CoreEndpointClassifier,
        IntentClassificationError,
        build_classification_request,
        classifier_config_from_settings,
        validate_classification,
    )
    from retriva_gateway.core.routing.pipeline import (
        apply_classification,
        apply_shadow,
        classification_context_hints,
    )
    from retriva_gateway.core.routing import (
        Route,
        get_workflow_context_registry,
        is_consequential_candidate,
        routing_metrics,
    )

    routed = eligible.routed
    # E-D1 final defense-in-depth assertion at the single classifier call
    # site: no recognized consequential operation or consequential
    # candidate may reach the classifier.  The deterministic engine and
    # guard pipeline are authoritative; this fails closed to
    # clarification WITHOUT invoking the classifier, never raises an
    # unhandled error, and does not create a second call site.
    if is_consequential_candidate(routed):
        metrics = routing_metrics()
        metrics.inc(
            "classifier_bypass_total", reason="consequential_candidate")
        return JSONResponse(content={
            "id": f"msg_{datetime.datetime.now().timestamp()}",
            "role": "assistant",
            "content": routed.clarification,
            "timestamp": datetime.datetime.now().isoformat(),
            "citations": [],
        })
    config = classifier_config_from_settings()
    # Privacy-safe categorical hints from the Phase C registry
    # (presence booleans + closed family hint ONLY).
    hints = classification_context_hints(
        get_workflow_context_registry(), eligible.key)
    request_payload = build_classification_request(
        eligible.message,
        max_input_chars=config.max_input_chars,
        ambiguity_class="WORKFLOW_ADJACENT",
        workflow_family_hint=hints["workflow_family_hint"],
        workflow_context_present=hints["workflow_context_present"],
        pending_confirmation_present=hints[
            "pending_confirmation_present"],
        correlation_id=corr_id)
    classifier = CoreEndpointClassifier(
        timeout_seconds=float(
            settings.AGENT_INTENT_CLASSIFIER_HTTP_TIMEOUT_SECONDS))
    metrics = routing_metrics()
    started = _time.perf_counter()
    failure_category = ""
    try:
        payload = await classifier.classify(request_payload)
        classification = validate_classification(payload)
    except IntentClassificationError as exc:
        failure_category = exc.category.value
        logger.info(
            f"[{corr_id}] intent_classification failed "
            f"category={failure_category}")
        classification = None
    except Exception:  # noqa: BLE001 — fail closed, no detail
        failure_category = "classifier_unavailable"
        logger.info(
            f"[{corr_id}] intent_classification failed "
            f"category={failure_category}")
        classification = None
    latency_s = _time.perf_counter() - started

    if classification is None:
        # Deterministic degradation: the routed (clarifying) result
        # stands exactly as the deterministic pipeline produced it.
        # Metrics record the failed call; shadow preserves the ring.
        metrics.inc("classifier_call_total", provider="core",
                    outcome="error")
        metrics.inc("classifier_failure_total", category=failure_category)
        metrics.observe_latency(latency_s)
        if failure_category == "regional_policy_rejected":
            metrics.inc("regional_policy_rejection_total")
        if settings.AGENT_INTENT_ROUTER_MODE == "shadow":
            apply_shadow(routed, None, failure_category=failure_category,
                         latency_s=latency_s)
        return JSONResponse(content={
            "id": f"msg_{datetime.datetime.now().timestamp()}",
            "role": "assistant",
            "content": routed.clarification,
            "timestamp": datetime.datetime.now().isoformat(),
            "citations": [],
        })
    logger.info(
        f"[{corr_id}] intent_classification ok "
        f"intent={classification.intent.value} "
        f"confidence={classification.confidence:.2f}")
    metrics.inc("classifier_call_total", provider="core", outcome="ok")
    metrics.observe_latency(latency_s)
    final = apply_classification(
        routed, classification,
        mode=settings.AGENT_INTENT_ROUTER_MODE, config=config)
    decision = final.decision
    metrics.inc("routing_decision_total", route=final.route.value,
                source="classifier")
    if final.route is Route.RAG:
        # Active narrow scope: ambiguous informational recommendation
        # may resolve to RAG — the request falls through to the plain
        # knowledge pipeline below (never a workflow, never the loop).
        return None
    if final.route is Route.AGENT_LOOP:
        # Active narrow scope: ambiguous SAFE-workflow recommendation
        # only — the guards and the tool boundary remain authoritative.
        return _AGENT_SENTINEL
    return JSONResponse(content={
        "id": f"msg_{datetime.datetime.now().timestamp()}",
        "role": "assistant",
        "content": final.clarification,
        "timestamp": datetime.datetime.now().isoformat(),
        "citations": [],
    })



async def _classify_and_apply(message, routed, routing, corr_id):
    """Phase D (Spec 001): the SINGLE authorized classifier call site.

    Builds the minimal privacy-safe request (the current normalized
    truncated message + categorical presence hints + prompt identity +
    trace correlation; NEVER history, tool results, domain payloads,
    resource IDs, tenant/principal/session/KB identity, confirmation
    data, or transport selection), calls the dedicated Core endpoint
    adapter, strictly re-validates the untrusted C2 response, and
    applies the accepted deterministic policy (pipeline.apply_
    classification).  On ANY failure the deterministic routed result
    stands unchanged (fail_mode=clarify); no failure may invoke
    another model, provider, endpoint, region, the reranker, RAG, or
    the agent loop.  Shadow keeps the deterministic route; active
    applies only the accepted narrow prerequisites.
    """
    from retriva_gateway.core.routing.classifier import (
        CoreEndpointClassifier,
        IntentClassificationError,
        build_classification_request,
        classifier_config_from_settings,
        validate_classification,
    )
    from retriva_gateway.core.routing.pipeline import (
        apply_classification,
        classification_context_hints,
    )
    config = classifier_config_from_settings()
    hints = classification_context_hints(
        routing.registry, routing.key)
    request_payload = build_classification_request(
        message,
        max_input_chars=config.max_input_chars,
        ambiguity_class="WORKFLOW_ADJACENT",
        workflow_family_hint=hints["workflow_family_hint"],
        workflow_context_present=hints[
            "workflow_context_present"],
        pending_confirmation_present=hints[
            "pending_confirmation_present"],
        correlation_id=corr_id)
    classifier = CoreEndpointClassifier(
        timeout_seconds=float(
            settings.AGENT_INTENT_CLASSIFIER_HTTP_TIMEOUT_SECONDS))
    try:
        payload = await classifier.classify(request_payload)
        classification = validate_classification(payload)
    except IntentClassificationError as exc:
        # Deterministic degradation: the routed (clarifying) result
        # stands; content-free log only (never the payload, the
        # message, or provider detail).
        logger.info(
            f"[{corr_id}] intent_classification failed "
            f"category={exc.category.value}")
        return routed
    except Exception:  # noqa: BLE001 — fail closed, no detail
        logger.info(
            f"[{corr_id}] intent_classification failed "
            f"category=classifier_unavailable")
        return routed
    logger.info(
        f"[{corr_id}] intent_classification ok "
        f"intent={classification.intent.value} "
        f"confidence={classification.confidence:.2f} "
        f"shadow={settings.AGENT_INTENT_ROUTER_MODE == 'shadow'}")
    return apply_classification(
        routed, classification,
        mode=settings.AGENT_INTENT_ROUTER_MODE, config=config)


async def _agent_chat(request: ChatRequest, corr_id: str, *,
                      legacy_error_body: bool = False,
                      claimed=None, resolved=None) -> JSONResponse:
    """Run the bounded agent loop (async; called from the chat endpoint).

    ``legacy_error_body`` preserves the exact legacy qualification-
    specific 503 body (mode ``off`` — the D5 rollback contract); the new
    pipeline (shadow/active) uses the generic family-neutral body (the
    D5 fix, Spec 001 Phase B).

    Phase C: ``claimed`` (server-only ClaimedConfirmationContext) is
    set on the trusted ToolContext for exactly this loop execution and
    cleared at its completion; ``resolved`` is an ordinary-context
    resource resolution exposed as a closed trusted-context line.  The
    workflow-context registry participates only in shadow/active (mode
    off never constructs, reads, or writes registry state).
    """
    from retriva_gateway.agent.loop import (
        AgentLoopError,
        run_agent_loop,
    )
    from retriva_gateway.agent.tools import ToolContext, build_default_tool_registry
    from retriva_gateway.core.routing import get_workflow_context_registry

    registry = build_default_tool_registry(
        allow_list=settings.AGENT_TOOL_ALLOWLIST or None
    )
    ctx = ToolContext(
        # Workflow-intent routing may enter agent mode without a
        # client session; attribute the turn to a synthesized
        # session derived from the correlation id.
        session_id=request.session_id or f"sess_{corr_id}",
        kb_id=request.kb_ids[0] if request.kb_ids else "default",
        allowed_attachment_ids=list(request.attachment_ids or []),
        correlation_id=corr_id,
        claimed_confirmation=claimed,
    )
    try:
        result = await run_agent_loop(
            user_message=request.message,
            registry=registry,
            ctx=ctx,
            kb_ids=request.kb_ids,
            metadata_filters=[f.model_dump() for f in (request.metadata_filters or [])],
            metadata_filter_mode=request.metadata_filter_mode.value,
            context_registry=(
                None if settings.AGENT_INTENT_ROUTER_MODE == "off"
                else get_workflow_context_registry()),
            resolved_reference=resolved,
        )
    except AgentLoopError as e:
        if legacy_error_body:
            return JSONResponse(status_code=503, content={
                "detail": (
                    f"Candidate qualification cannot be executed from this chat: "
                    f"{e}. I will not simulate scores or Web Research results."
                )
            })
        return JSONResponse(status_code=503, content={
            "detail": (
                f"The requested workflow cannot be executed from this chat: "
                f"{e}. I will not simulate or guess workflow results."
            )
        })
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[{corr_id}] agent loop failed")
        return JSONResponse(status_code=502, content={
            "detail": f"Agent loop failed: {e}",
        })
    finally:
        # Phase C (addendum D-3): the server-only claimed context is
        # scoped to ONE agent-loop execution — cleared when the loop
        # ends, on every path (normal, typed-error, exception).
        ctx.claimed_confirmation = None
    return JSONResponse(content={
        "id": f"msg_{datetime.datetime.now().timestamp()}",
        "role": "assistant",
        "content": result.content,
        "timestamp": datetime.datetime.now().isoformat(),
        "citations": [],
        "agent": {
            "iterations": result.iterations,
            "stopped_reason": result.stopped_reason,
            "tool_calls": result.tool_calls_executed,
        },
    })


def _transform_citations(core_sources: list) -> list:
    citations = []
    for idx, src in enumerate(core_sources):
        source_dict = src.get("source", {})
        name = source_dict.get("name", "Unknown")
        source_url = source_dict.get("url", "")
        doc_snippets = src.get("document", [])
        meta_list = src.get("metadata", [])
        doc_id = meta_list[0].get("source", "") if meta_list else ""
        text = "\n".join(doc_snippets)[:500]
        citation = {
            "id": str(idx + 1),
            "document_id": doc_id,
            "filename": name,
            "text": text,
        }
        if source_url:
            citation["source_url"] = source_url
        citations.append(citation)
    return citations


@router.post("/chat")
async def chat(request: ChatRequest):
    corr_id = get_correlation_id() or "unknown"
    kb_ids = request.kb_ids
    message = request.message
    stream = request.stream

    # Agent mode: bounded tool-calling loop over typed extension tools.
    # Only when explicitly requested (tools_enabled + session_id) and
    # enabled in config; plain chat otherwise (backward compatible).
    # Spec 001 Phase B: mode off keeps the legacy router (and the exact
    # legacy D5 503 body); shadow/active use the deterministic pipeline
    # (generic family-neutral 503 body) and may return a typed
    # clarification instead of entering the loop.
    agent_result = _run_agent_mode(request, corr_id)
    if isinstance(agent_result, _ClassifierEligible):
        # Phase D: the SINGLE authorized classifier call site (async —
        # this function is async; _run_agent_mode stays synchronous).
        agent_result = await _resolve_classification(
            agent_result, corr_id)
        if agent_result is None:
            # Active narrow scope resolved to RAG: fall through to the
            # plain knowledge pipeline below.
            pass
        else:
            return agent_result
    if agent_result is _AGENT_SENTINEL:
        return await _agent_chat(
            request, corr_id,
            legacy_error_body=(settings.AGENT_INTENT_ROUTER_MODE == "off"))
    if isinstance(agent_result, _AgentAdmission):
        # Phase C: agent-loop admission carrying the server-only
        # claimed execution context and/or the ordinary resolved
        # reference (never model-visible; set only by the Gateway).
        return await _agent_chat(
            request, corr_id,
            legacy_error_body=False,
            claimed=agent_result.claimed,
            resolved=agent_result.resolved)
    if agent_result is not None:
        return agent_result

    # Priority: metadata_filters (list) > filters (dict)
    explicit_filters = request.metadata_filters or request.filters or []
    mode = request.metadata_filter_mode

    try:
        metadata_filter_mode = FilterManager.validate_mode(mode)
    except ValueError as e:
        logger.error(f"[{corr_id}] Invalid metadata_filter_mode: {mode}")
        return JSONResponse(status_code=400, content={"detail": str(e)})

    # As per SDD architectural revision: No inference. 
    # Use explicit filters provided by the UI only.
    try:
        normalized_filters = await FilterManager.normalize_v2(explicit_filters)
    except ValueError as e:
        logger.error(f"[{corr_id}] Filter normalization failed: {e}")
        return JSONResponse(status_code=400, content={"detail": str(e)})
    
    core_payload = {
        "model": "retriva",
        "messages": [{"role": "user", "content": message}],
        "kb_ids": kb_ids,
        "metadata_filters": normalized_filters,
        "metadata_filter_mode": metadata_filter_mode,
        "stream": stream
    }

    logger.info(f"[{corr_id}] Chat routing: direct RAG. mode={metadata_filter_mode}, filters={normalized_filters}")

    try:
        if stream:
            gen = await core_client.chat_completions(core_payload, stream=True)
            return StreamingResponse(gen, media_type="text/event-stream")
        else:
            core_response = await core_client.chat_completions(core_payload, stream=False)
            choice = core_response.get("choices", [{}])[0]
            choice_message = choice.get("message", {})
            raw_sources = core_response.get("sources", [])
            citations = _transform_citations(raw_sources)
            
            web_ui_message = {
                "id": core_response.get("id", f"msg_{datetime.datetime.now().timestamp()}"),
                "role": "assistant",
                "content": choice_message.get("content", ""),
                "timestamp": datetime.datetime.now().isoformat(),
                "citations": citations
            }
            return JSONResponse(content=web_ui_message)
    except Exception as e:
        logger.error(f"[{corr_id}] Chat forwarding failed: {e}")
        raise
