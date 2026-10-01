# Plan — Hybrid Intent Routing (Spec 001)

Governing ADR: ADR-0002. Every phase lands with deterministic tests and ends
in a gate; phases do not proceed past a failed gate (constitution §38).

## Phase A — governance gate (this delivery)

Constitutional report, this pack, ADR-0002 presented to the owner.
**Gate A: owner accepts spec.md, architecture.md, plan.md, tasks.md,
acceptance.md, ADR-0002.** No code before acceptance.

## Phase B — taxonomy + deterministic engine

- routing package skeleton (taxonomy, deterministic engine, guards,
  clarifications); legacy-equivalent mode `off` wired into chat.py behind
  zero behavior change; D2/D3/D5 fixes land here (doc-framing veto,
  narrowed enrichment rules, generic 503).
- Tests: deterministic routing cases 1-14 + near-pairs; existing suites
  green.

**Gate B: full existing gateway test suite + new deterministic tests pass;
mode `off` proven behavior-identical (compatibility cases 61-68).**

## Phase C — workflow context + explicit-intent guards

- context registry (TTL/bounded/tenant-scoped), tool-outcome observer,
  guard integration; D1 fixed (production-armed context enables typed
  follow-ups like "yes, enrich them" and "approve it" only under guard).
- Tests: cases 29-39 (explicit consequential intent, pending confirmation,
  cross-tenant rejection).

**Gate C: guard and context tests pass; zero consequential route without
explicit intent.**

## Phase D — classifier transport (Core) + gateway interface

- Core `INTENT_CLASSIFIER_*` config + strict startup validation + EU
  enforcement + internal endpoint; gateway classifier interface, validation,
  failure taxonomy; `.env.example` + deployment compose plumbing.
- Tests: cases 15-28 (boundary), security cases 40-48.

**Gate D: classifier boundary + security tests pass; disabled/failed
classifier reproduces deterministic behavior.**

## Phase E — decision policy, shadow mode, metrics, streaming

- policy integration (modes off/shadow/active), content-free metrics +
  internal status endpoint, streaming typed error (C5, D4 fix),
  clarification templates.
- Tests: cases 49-54 (typed errors), 55-60 (multilingual), streaming
  compatibility.

**Gate E: all deterministic tests green; shadow mode proven route-neutral.**

## Phase F — evaluation dataset + shadow acceptance

- dataset-v1 (synthetic EN/IT, classes and near-pairs per spec §20),
  evaluation harness, metric report, safety-first gates (spec §22).
- Shadow acceptance review with the owner: classifier-vs-deterministic
  comparison on the dataset; zero route changes; recall improvement
  evidence.

**Gate F: dataset gates pass; owner accepts shadow-mode evidence and
authorizes `active` for ambiguous informational + safe proposal routes
only.**

## Phase G — active hybrid (limited) + deployed acceptance

- Enable `active` in the isolated deployment tenant (synthetic data;
  cust_0007 untouched); deployed walkthrough per acceptance.md (25 checks);
  provider/model/region/calls/latency/cost recorded as safe bounded
  metadata.

**Gate G: deployed acceptance passes; delivery report written
(docs/hybrid-intent-routing.md + -delivery.md); rollback switch proven.**
