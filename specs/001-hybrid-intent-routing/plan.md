# Plan — Hybrid Intent Routing (Spec 001, revision 2)

Governing ADR: ADR-0002 (revision 2). Every phase lands with deterministic
tests and ends in a gate; phases do not proceed past a failed gate
(constitution §38). No phase begins before the revised pack and ADR are
explicitly accepted (gate A).

## Phase A — governance gate (this delivery)

Constitutional report, this pack, ADR-0002 presented to the owner; owner
review "accept with changes" applied as revision 2 (spec §Revision 2
summary); reranker governance defect recorded separately as GF-001
(`retriva-core/docs/governance/GF-001-dangling-reranker-adr-reference.md`,
outside this pack's scope, unresolved here).
**Gate A: owner accepts the revised spec.md, architecture.md, plan.md,
tasks.md, acceptance.md, and ADR-0002 (revision 2), including the
Constitution §11 compatibility interpretation and the narrowed active-mode
authority.** No code before acceptance. GF-001 resolution proceeds
independently through its own governance process and does not block gate A.

## Phase B — taxonomy + deterministic engine

- routing package skeleton (taxonomy, deterministic engine, guards,
  clarifications); the new pipeline is wired into chat.py gated on modes
  `shadow`/`active`; mode `off` keeps the legacy router and its exact
  externally observable behavior (spec §Activation model).
- D2/D3/D5 fixes land here **in the new pipeline** (doc-framing veto,
  narrowed enrichment rules, generic family-neutral 503): externally
  effective only in `shadow`/`active`; `off` preserves the exact legacy
  qualification-specific 503 body (D5) so `off` remains a genuine
  behavioral rollback.
- deterministic engine includes the MULTI-INTENT rule (conjunction/
  sequencing detection → clarification, never partial execution) and the
  workflow-adjacent vs non-adjacent AMBIGUOUS split.
- Tests: deterministic routing cases 1-14 + near-pairs; existing suites
  green; TR1 (workflow-dispatch-only influence) and the dispatch components
  of TR5/TR6. TR2-TR4 (provider/model/endpoint/region immutability) are
  proven completely only at Gate D, where the classifier transport and its
  request shape exist; Phase B may establish configuration prerequisites
  but must not claim complete proof of TR2-TR4 (dossier O-1).

**Gate B: full existing gateway test suite + new deterministic tests pass;
mode `off` proven behavior-identical (compatibility cases 61-68, TR84:
legacy routing, streaming, and the exact legacy D5 503 body); TR1 and the
TR5/TR6 dispatch components green.**

## Phase C — workflow context + explicit-intent guards

- context registry (TTL/bounded/tenant-scoped, deterministic eviction per
  spec C4: expired-first purge, typed fail-closed rejection at capacity, no
  silent eviction of live confirmations or contexts, content-free
  capacity/rejection metrics, no spill into an unapproved persistent
  store), tool-outcome observer, guard integration; D1 fixed in the new
  pipeline (production-armed context enables typed follow-ups like "yes,
  enrich them" and "approve it" only under guard; active in `shadow`/
  `active` per the activation model).
- pending-confirmation sub-record with the full C4 binding (tenant,
  principal/session, family, operation, resource type, opaque ID, version,
  previous authoritative state, allowed next transition, created_at,
  expiry, correlation ID); single-use; invalidated on authoritative state
  change; re-validated against current server state; classifier never
  creates or modifies it.
- multi-intent policy B wired end-to-end (clarify, execute nothing).
- Tests: cases 29-39 (explicit consequential intent, pending confirmation,
  cross-tenant rejection); TR59-TR66 (multi-intent, EN/IT); TR67-TR74
  (pending confirmation binding and lifecycle); TR81-TR83 (registry
  eviction).

**Gate C: guard and context tests pass; zero consequential route without
explicit intent; zero consequential execution from multi-intent messages;
zero bare-affirmative action without a valid typed confirmation; registry
bounds enforced fail-closed (TR81-TR83).**

## Phase D — classifier transport (Core) + gateway interface

- Core `INTENT_CLASSIFIER_*` config + strict startup validation + EU
  enforcement + internal endpoint; gateway classifier interface, validation,
  failure taxonomy; `.env.example` + deployment compose plumbing.
- endpoint trust boundary per spec C6/architecture 6b: service-to-service
  authentication, internal binding, request/rate/concurrency bounds,
  content-type enforcement, cooperative cancellation, content-free logging,
  sanitized errors, degraded status; external exposure requires typed
  contract + OpenAPI first.
- no-recursion controls per architecture 6c: dedicated transport, purpose
  marker, single call site, no tool access in the classification path.
- Tests: cases 15-28, 40-48; TR2-TR4 complete (Constitution §11 boundary:
  provider/model/endpoint/region provably config-selected — provable here
  because the transport and its request shape now exist) plus the
  provider-selection components of TR5/TR6; TR7-TR14 (endpoint trust
  boundary); TR15-TR21 (ownership + direct/indirect recursion); TR42-TR44,
  TR49 (confidence validation + bounds at config level).

**Gate D: classifier boundary + security + trust-boundary + recursion tests
pass; TR2-TR4 green; disabled/failed classifier reproduces deterministic
behavior; no other model invoked implicitly on failure.**

## Phase E — decision policy, shadow mode, metrics, streaming

- policy integration (modes off/shadow/active; narrowed active authority:
  ambiguous informational, non-destructive analysis, proposal creation,
  clarification selection only — consequential operations guard-only);
  content-free metrics + internal status endpoint; streaming policy 7.1/
  7.2/7.3 (typed 409 `workflow_stream_unsupported` with machine-readable
  retry; neutral streamed clarification for workflow-adjacent ambiguous; no
  classifier on streaming); clarification templates incl. multi-intent.
- confidence semantics implemented (>= threshold, exact boundary, malformed
  rejection, conflict rejection, never-override rules, process-global
  thresholds).
- shadow records restricted to the spec §Shadow-mode privacy allowlist;
  ephemeral bounded diagnostics only.
- Tests: cases 49-54, 55-60, streaming compatibility, metrics content-free
  assertions; TR22-TR28 (streaming); TR29-TR39 (active authority);
  TR40-TR41, TR45-TR48, TR50 (confidence); TR51-TR58 (shadow privacy);
  TR75-TR80 (failure behavior); TR85-TR87 (mode gating: shadow activates
  the fixes without classifier route influence; active adds only the
  narrowed influence; rollback to `off` restores legacy behavior exactly).

**Gate E: all deterministic tests green; shadow mode proven route-neutral
(with respect to classifier recommendations — the deterministic route is
unchanged by classifier output; not a claim of legacy-identical routing)
and privacy-safe; streaming behavior exactly as specified (no tool, no
simulation, typed retry).**

## Phase F — evaluation dataset + shadow acceptance

- dataset-v1 (synthetic EN/IT, classes and near-pairs per spec §20,
  including multi-intent pairs TR59-TR66 and bare-affirmative pairs TR67),
  evaluation harness, metric report, safety-first gates (spec §22;
  multi-intent and confirmation rates must be zero where required).
- Shadow acceptance review with the owner: classifier-vs-deterministic
  comparison on the dataset; zero route changes; recall improvement
  evidence.

**Gate F: dataset gates pass; owner accepts shadow-mode evidence and
authorizes `active` for ambiguous informational + safe proposal routes
only (narrowed authority list read into the record).**

## Phase G — active hybrid (limited) + deployed acceptance

- Enable `active` in the isolated deployment tenant (synthetic data;
  cust_0007 untouched); deployed walkthrough per acceptance.md (25 original
  checks + revision-2 additions 26-34); provider/model/region/calls/
  latency/cost recorded as safe bounded metadata.

**Gate G: deployed acceptance passes (items 1-33); delivery report written
(docs/hybrid-intent-routing.md + -delivery.md); rollback switch proven.**
