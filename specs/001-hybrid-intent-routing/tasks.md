# Tasks — Hybrid Intent Routing (Spec 001, revision 2)

## Phase A — governance gate

- [x] Constitutional report delivered (rules affected, governing docs,
      substantial-work determination, conflicts D1-D5, verified routing
      inventory, observable contracts, provider/regional boundaries, scope).
- [x] spec.md / architecture.md / plan.md / tasks.md / acceptance.md drafted.
- [x] ADR-0002 drafted.
- [x] Owner review received: "accept with changes" — revision 2 applied
      (spec §Revision 2 summary: §11 compatibility, endpoint trust
      boundary, Gateway/Core split, no-recursion, streaming policy,
      narrowed active authority, confidence policy, shadow privacy, failure
      behavior, multi-intent, pending confirmation, governing invariant,
      TR matrix).
- [x] Reranker governance defect recorded separately as GF-001
      (`retriva-core/docs/governance/GF-001-dangling-reranker-adr-reference.md`);
      not fixed here; ADR-0002 does not govern reranking; no constitution
      amendment proposed by this pack.
- [x] Revision-2 repair applied (owner acceptance dossier): SD-1/SD-2
      (decision tables split into legacy `off` table and new-pipeline
      `shadow`/`active` table), SD-3 (A67 split into A67a-A67e), SD-4
      (normative activation model incl. the D5 resolution: generic 503 in
      `shadow`/`active` only, exact legacy 503 body in `off`), O-1 (TR2-TR4
      complete-proof moved to Phase D/Gate D), O-2 (registry eviction
      policy + TR81-TR83), O-5 (TR numbering provenance note); TR84-TR87
      added for mode gating and rollback.
- [x] Owner accepts the revised pack + ADR-0002 — Owner Acceptance Gate A
      APPROVED 2026-10-01 (revision 2 as corrected; §11 interpretation,
      activation model, narrowed active authority, streaming, multi-intent,
      consequential boundary, pending confirmation, confidence policy,
      endpoint trust boundary, privacy/observability, registry capacity
      behavior, TR1-TR87 traceability, GF-001 accepted as an unresolved
      record only). Gate recorded in spec.md Status + ADR Status. Approval
      covers the documentation baseline only; no implementation,
      activation, deployment, provider/model change, paid-provider use,
      merge, release, or GF-001 resolution is authorized until the
      applicable subsequent gate is explicitly approved.

## Phase B — taxonomy + deterministic engine

- [ ] `core/routing/taxonomy.py`: closed enums, `RoutingDecision`,
      `IntentClassification` (extra=forbid, schema_version "1").
- [ ] `core/routing/deterministic.py`: typed rule list R-DOC-FRAMING,
      R-NEGATION, R-HYPOTHETIC, R-QUOTED (incl. code fences), R-COMMAND
      (narrowed families), R-QUESTION, R-MULTI-INTENT (conjunction/
      sequencing → clarification), R-FOLLOWUP, R-UNSUPPORTED; EN/IT
      normalization; workflow-adjacent vs non-adjacent AMBIGUOUS split;
      reason codes.
- [ ] `core/routing/clarifications.py`: closed template set (incl.
      multi-intent template listing detected families only).
- [ ] `chat.py`: pipeline integration gated on `AGENT_INTENT_ROUTER_MODE`
      `shadow`/`active`; mode `off` keeps the legacy router with exact
      legacy externally observable behavior (incl. the qualification-
      specific agent-unavailable 503 body, D5); generic family-neutral
      agent-unavailable 503 text in the new pipeline only.
- [ ] Tests: routing cases 1-14; near-pairs (approve/explain, import,
      commit, activate, prompt-writing); compatibility 61-68 + TR84 (off =
      legacy routing, streaming, and exact D5 503 body); TR1 and the
      dispatch components of TR5/TR6 (TR2-TR4 complete proof deferred to
      Phase D per dossier O-1).
- [x] Gate B correction applied (owner decisions D-1–D-4): D-1 negation
      scope for every recognized workflow operation verb (EN/IT tests
      TR88); D-2 informational/multi-intent corners (TR89, TR90, TR91);
      D-3 C1 enrichment extension — ACP_EVIDENCE_ENRICHMENT /
      ACP_EVIDENCE_ENRICHMENT_STATUS / ACP_EVIDENCE_ACCEPTANCE per the
      accepted `agent/tools.py` ToolDefinitions (destructive=True for
      request and acceptance; read-only status) and ADR-024 decisions
      4/6 (TR92-TR94); import rejection and ACP deactivation remain
      outside C1 (fail-closed); D-4 baseline-relative Gate B compatibility
      policy recorded in plan Gate B.

## Phase C — workflow context + guards

- [ ] `core/routing/context.py`: bounded TTL registry, tenant/session/kb
      keying, destructive invalidation, inconsistency handling;
      deterministic eviction per spec C4 (expired-first purge; typed,
      sanitized, fail-closed rejection at capacity; no silent eviction of
      live confirmations or contexts; content-free capacity/rejection
      metrics; no spill into an unapproved persistent store);
      pending-confirmation sub-record with the full C4 binding (tenant,
      principal/session, family, operation, resource type, opaque ID,
      version, previous authoritative state, allowed next transition,
      created_at, expiry, correlation ID), single-use, invalidated on
      authoritative state change, re-validated against current server
      state.
- [ ] Tool-outcome observer hook in the agent loop result path (typed
      classes only).
- [ ] `core/routing/guards.py`: explicit-intent guard, negation/hypothetical/
      quoted awareness, pending-confirmation validation (fail closed on
      cross-tenant/expired/mismatched/stale), multi-intent split (policy B:
      clarify, execute nothing); classifier reference-resolution may match
      but never create/modify confirmations.
- [ ] Tests: cases 29-39; TR59-TR66 (multi-intent EN/IT); TR67-TR74
      (confirmation binding + lifecycle); TR81-TR83 (registry eviction).

## Phase D — classifier transport + interface

- [ ] Core config domain `INTENT_CLASSIFIER_*` (defaults, bounds, secret
      handling, request/rate/concurrency limits, service auth token) +
      `model_post_init` validation mirroring reranking.
- [ ] Core transport (OpenRouter EU endpoint / Bedrock regional) + strict
      startup validation + degraded status section; on failure, typed
      sanitized error only — never an implicit invocation of the chat
      model, RAG model, visual model, reranker, another provider, or a
      global/lower-security endpoint.
- [ ] Core internal endpoint `POST /v1/intent/classification` with versioned
      prompt, injection framing, strict JSON validation, typed errors, and
      the full C6 trust boundary: service-to-service authentication,
      internal binding (not published by default; Gateway does not proxy;
      browser access rejected), request-size/context/timeout/retry/
      concurrency/rate limits, content-type enforcement, cooperative
      cancellation, content-free logging, error sanitization, readiness
      isolation; public OpenAPI exclusion enforced by auth + binding, not
      obscurity; external exposure requires typed contract + OpenAPI first.
- [ ] No-recursion controls: dedicated transport (never
      `/v1/chat/completions`), purpose marker
      `X-Retriva-Internal-Purpose: intent-classification`, single call site,
      no tool access in the classification path, bounded failure handling.
- [ ] Gateway `core/routing/classifier.py`: protocol, config, core adapter,
      full re-validation (incl. missing/NaN/infinity/string/out-of-range
      confidence and field conflicts), `IntentClassificationError`
      categories.
- [ ] `core/client.py`: classification POST with service credential +
      purpose marker + correlation ID.
- [ ] `.env.example`, deployment compose env plumbing (mode default off).
- [ ] Tests: cases 15-28, 40-48; TR2-TR4 complete (Constitution §11
      boundary: provider/model/endpoint/region provably config-selected
      against the real transport request shape) + the provider-selection
      components of TR5/TR6; TR7-TR14 (endpoint trust); TR15-TR21
      (ownership + recursion); TR42-TR44, TR49 (confidence validation).

## Phase E — policy, shadow, metrics, streaming

- [ ] `core/routing/policy.py`: full decision table incl. mode off/shadow/
      active, classifier-failure fallback, MULTI-INTENT clarify, and the
      narrowed active-mode authority (ambiguous informational, ambiguous
      non-destructive analysis, ambiguous proposal creation, clarification
      selection only; consequential operations guard-only; classifier may
      identify family / flag concern / request focused clarification /
      identify needed typed context — never route into the tool).
- [ ] Confidence semantics: `>=` threshold (exact boundary tested),
      separate safe-workflow threshold (≥ informational), no consequential
      threshold path representable, never-override rules (negation,
      quotation, hypothetical, guards, state, permissions, tenant, region),
      process-global thresholds only.
- [ ] `core/routing/metrics.py` + `api/internal_routing.py` status endpoint
      (auth-protected, bounded, content-free); shadow records restricted to
      the spec §Shadow-mode privacy allowlist (confidence buckets, not raw;
      no identifiers, no content); ephemeral bounded diagnostics only; no
      persistent message-level corpus.
- [ ] Streaming: 7.1 unchanged cited RAG; 7.2 deterministic workflow
      detection → typed 409 `workflow_stream_unsupported` with
      machine-readable retry (family, mode, action, endpoint, correlation
      ID, reason; no raw content or tool args); 7.3 no classifier call —
      workflow-adjacent ambiguous → neutral streamed clarification,
      non-adjacent → unchanged SSE; mode off = legacy exactly.
- [ ] Tests: cases 49-54, 55-60, streaming compatibility, metrics
      content-free assertions; TR22-TR28; TR29-TR39; TR40-TR41, TR45-TR48,
      TR50; TR51-TR58; TR75-TR80; TR85-TR87 (mode gating: shadow activates
      the fixes without classifier route influence; active adds only the
      narrowed influence; rollback to `off` restores legacy behavior
      exactly).

## Phase F — evaluation + shadow acceptance

- [ ] `eval/intent-routing/dataset-v1.json` + schema + README (synthetic,
      EN/IT, all required classes and near-pairs, injection cases,
      multi-intent pairs TR59-TR66, bare-affirmative pairs TR67; no
      confidential production data — TR58).
- [ ] Evaluation harness (offline, deterministic fakes) + metric report;
      safety-first gates (spec §22; multi-intent consequential-execution
      rate and confirmation-without-typed-state rate must be zero).
- [ ] Shadow acceptance run + owner review gate (route-neutral +
      privacy-safe evidence).

## Phase G — active hybrid + deployed acceptance

- [ ] Enable `active` (isolated tenant, synthetic data; cust_0007
      untouched); run deployed acceptance checklist (items 1-25 +
      revision-2 additions 26-34).
- [ ] Prove rollback switch (mode off → the legacy router and legacy
      externally observable behavior — routing, streaming, and the exact
      legacy D5 503 body — restored exactly) on the deployed instance.
- [ ] Documentation set (spec §Documentation) + delivery report +
      `CLOSURE.md`-style milestone record.
