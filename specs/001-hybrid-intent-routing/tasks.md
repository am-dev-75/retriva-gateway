# Tasks — Hybrid Intent Routing (Spec 001)

## Phase A — governance gate

- [ ] Constitutional report delivered (rules affected, governing docs,
      substantial-work determination, conflicts D1-D5, verified routing
      inventory, observable contracts, provider/regional boundaries, scope).
- [ ] spec.md / architecture.md / plan.md / tasks.md / acceptance.md drafted.
- [ ] ADR-0002 drafted.
- [ ] Owner accepts pack + ADR (gate recorded in spec.md Status + ADR).

## Phase B — taxonomy + deterministic engine

- [ ] `core/routing/taxonomy.py`: closed enums, `RoutingDecision`,
      `IntentClassification` (extra=forbid, schema_version "1").
- [ ] `core/routing/deterministic.py`: typed rule list R-DOC-FRAMING,
      R-NEGATION, R-HYPOTHETIC, R-QUOTED (incl. code fences), R-COMMAND
      (narrowed families), R-QUESTION, R-FOLLOWUP, R-UNSUPPORTED;
      EN/IT normalization; reason codes.
- [ ] `core/routing/clarifications.py`: closed template set.
- [ ] `chat.py`: pipeline integration behind `AGENT_INTENT_ROUTER_MODE=off`
      with legacy-identical behavior; generic agent-unavailable 503 text.
- [ ] Tests: routing cases 1-14; near-pairs (approve/explain, import,
      commit, activate, prompt-writing); compatibility 61-68.

## Phase C — workflow context + guards

- [ ] `core/routing/context.py`: bounded TTL registry, tenant/session/kb
      keying, destructive invalidation, inconsistency handling.
- [ ] Tool-outcome observer hook in the agent loop result path (typed
      classes only).
- [ ] `core/routing/guards.py`: explicit-intent guard, negation/hypothetical/
      quoted awareness, pending-confirmation validation, multi-intent split.
- [ ] Tests: cases 29-39 including expired/mismatched confirmation and
      cross-tenant context rejection.

## Phase D — classifier transport + interface

- [ ] Core config domain `INTENT_CLASSIFIER_*` (defaults, bounds, secret
      handling) + `model_post_init` validation mirroring reranking.
- [ ] Core transport (OpenRouter EU endpoint / Bedrock regional) + strict
      startup validation + degraded status section.
- [ ] Core internal endpoint `POST /v1/intent/classification` with versioned
      prompt, injection framing, strict JSON validation, typed errors.
- [ ] Gateway `core/routing/classifier.py`: protocol, config, core adapter,
      full re-validation, `IntentClassificationError` categories.
- [ ] `core/client.py`: classification POST with trusted headers +
      correlation ID.
- [ ] `.env.example`, deployment compose env plumbing (mode default off).
- [ ] Tests: cases 15-28, 40-48 (incl. forged header stripping unchanged,
      injection resistance, tenant/permission/tool-arg absence).

## Phase E — policy, shadow, metrics, streaming

- [ ] `core/routing/policy.py`: full decision table incl. mode off/shadow/
      active and classifier-failure fallback.
- [ ] `core/routing/metrics.py` + `api/internal_routing.py` status endpoint
      (auth-protected, bounded, content-free).
- [ ] Streaming: deterministic workflow detection → typed 409
      `workflow_stream_unsupported`; ambiguous/informational → unchanged SSE.
- [ ] Tests: cases 49-54, 55-60, streaming compatibility, metrics
      content-free assertions.

## Phase F — evaluation + shadow acceptance

- [ ] `eval/intent-routing/dataset-v1.json` + schema + README (synthetic,
      EN/IT, all required classes and near-pairs, injection cases).
- [ ] Evaluation harness (offline, deterministic fakes) + metric report;
      safety-first gates (spec §22).
- [ ] Shadow acceptance run + owner review gate.

## Phase G — active hybrid + deployed acceptance

- [ ] Enable `active` (isolated tenant, synthetic data; cust_0007
      untouched); run deployed acceptance checklist (25 items).
- [ ] Prove rollback switch (mode off → deterministic-only) on the deployed
      instance.
- [ ] Documentation set (spec §Documentation) + delivery report +
      `CLOSURE.md`-style milestone record.
