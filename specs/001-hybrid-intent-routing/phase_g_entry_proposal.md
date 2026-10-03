# Phase G Entry Proposal — Hybrid Intent Routing (Spec 001 / ADR-0002)

- **Status:** PROPOSAL (entry authorization requested; implementation not started)
- **Date:** 2026-10-03
- **Deciders:** Retriva owner (user), Kilo (code agent)
- **Derived from:** accepted Spec 001 pack (revision 2) — `spec.md`, `architecture.md`,
  `plan.md`, `tasks.md`, `acceptance.md`; ADR-0002 (revision 2, ACCEPTED);
  ADR-026 (ConfirmationReadyOutcome, prerequisite to Phase C, accepted at C0-A/C0);
  the canonical Retriva constitution v1.1 (`retriva-core/.agent/rules/retriva-constitution.md`,
  highest authority); and accepted Gates **B, C0-A, C0, C, D, E, and F**.
- **Governing relationship:** constitution §4/§37/§38 (phase gating, done-means-accepted),
  §9/§18 (control/data plane, optional capability), §11 (provider/model neutrality),
  §31 (data sovereignty, no fallback), §33/§34 (no leakage, secrets referenced), §41
  (internal observability stays internal); plan.md Gate G; acceptance.md
  "Active-hybrid acceptance (Phase G)" and "Deployed acceptance (Phase G)".
- **Prerequisite state (verified):** Gate F accepted 2026-10-03 on the owner-approved
  baseline-relative, zero-regression basis. Commits `377cfde`, `ddc7697`, `b52e0c4`,
  `f9210ab`, `4336588` are accepted and MUST NOT be amended/squashed/rebased/merged/pushed.
  `4336588` is the HEAD of branch `phase_f_evaluation`. All prior gates B–F are accepted;
  the runtime pipeline (deterministic engine, guards, context registry, classifier
  interface, policy, metrics, streaming, shadow) is carried forward unchanged as the
  system under test. Phase G is the **deployment + active-enablement + deployed acceptance**
  phase; it introduces **no new routing behavior** beyond what Gates B–F already accepted.

> Scope boundary carried from Gate F acceptance: Phase G does NOT modify runtime source,
> the dataset, the dataset schema, the threshold artifact, the consequential-candidate
> contract, the classifier-bypass vocabulary, Core/CRM Assistant files outside the
> already-accepted scope, or ADR-0002. It enables `active` in an isolated deployment
> tenant, runs the owner-reviewed deployed acceptance walkthrough (acceptance.md items
> 1–34), proves the rollback switch, and writes the delivery report. It does not
> authorize production-wide rollout, merge, release, baseline-defect correction,
> persistent classifier/confirmation storage beyond the accepted in-process registry,
> multi-instance registry synchronization, or GF-001 resolution.

---

## 1. Exact Phase G name and Gate G criteria

**Name:** *Phase G — Active Hybrid (Limited) + Deployed Acceptance.*

**Gate G criteria (normative, from plan.md Gate G and acceptance.md "Active-hybrid
acceptance" + "Deployed acceptance"):**

1. `active` is enabled only in an isolated deployment tenant; synthetic data; `cust_0007`
   untouched (acceptance.md "Deployed acceptance", plan.md Phase G).
2. `active` influences **only** the accepted ambiguous safe routes: ambiguous informational
   routing, ambiguous non-destructive analysis, ambiguous proposal creation, clarification
   selection (TR29–TR31). Consequential operations still require the deterministic explicit-
   intent guard (A29–A39 and TR32–TR39 re-run in active mode).
3. Deployed acceptance checklist items 1–34 pass (deterministic→agent, doc→RAG, ambiguous→EU
   classifier with verified provider/model/region, ambiguous informational→RAG, ambiguous
   proposal→agent/clarify, ambiguous activation does not activate, explicit activation still
   requires state+permission, negation/hypothetical/quoted do not execute, KB/metadata no
   influence, forged principal stripped, typed workflow failure no RAG fallback, classifier
   failure no global route, classifier-disabled restores deterministic-only, shadow route-
   neutral, active changes only accepted ambiguous safe routes, metrics/status content-free,
   audit correlation, in-process persistence semantics, RAG citations unchanged; plus
   revision-2 items 26–34: external/unauthenticated endpoint rejected, typed
   `workflow_stream_unsupported` retry, neutral ambiguous-streaming clarification, multi-intent
   clarifies and executes nothing, bare-affirmative activation requires typed pending
   confirmation with expiry enforced, exact-threshold spot-check, shadow-record allowlist
   inspection, mode `off` restores legacy streaming exactly, mode `off` preserves the exact
   legacy D5 503 body and legacy non-streaming routing).
4. Rollback switch (`AGENT_INTENT_ROUTER_MODE=off`) proven on the deployed instance: restores
   the legacy router and legacy externally observable behavior exactly (TR84, TR87) without
   reactivating client opt-in or arbitrary workflow selection.
5. Safety-zero invariants hold under live operation: mutation-intent false-positive = 0,
   multi-intent consequential-execution = 0, cross-tenant context acceptance = 0,
   classifier-driven authorization = 0, disallowed-region fallback = 0, content leakage = 0.
6. Provider/model/region selection is deployment-global validated configuration (constitution
   §11); EU residency and ZDR enforced with no fallback (constitution §31; spec C6/C7).
7. Delivery report written (`docs/hybrid-intent-routing.md` + `-delivery.md`) and a
   `CLOSURE.md`-style milestone record produced.

---

## 2. Repositories and branches in scope

- **retriva-gateway** — control plane; owns the mode switch `AGENT_INTENT_ROUTER_MODE`,
  `AGENT_INTENT_CLASSIFIER_*` policy config, the internal routing-status endpoint, and the
  routing pipeline carried forward from accepted Gates B–F. Phase G changes **no routing
  source**; it only enables `active` via deployment configuration and writes delivery docs.
- **retriva-core** — data plane; owns the `INTENT_CLASSIFIER_*` transport and the internal
  endpoint `POST /v1/intent/classification` (spec C6, architecture §6b/§6c). Phase G changes
  **no Core source**; the transport is already implemented and accepted at Gate D. The
  deployment `.env`/compose enable it.
- **retriva-local-containerized-deployment** — the supported containerized deployment; its
  `docker-compose.yml` already wires `INTENT_CLASSIFIER_ENABLED` (Core, default `false`),
  `AGENT_INTENT_CLASSIFIER_ENABLED` (Gateway, default `false`), and the full `INTENT_CLASSIFIER_*`
  block (EU residency + ZDR flags, service auth token, OpenRouter EU base URL, Bedrock
  `eu-central-1`). Phase G changes the **deployment `.env`** (enable classifier + set mode
  `active` for the isolated tenant) and verifies the compose wiring; no schema/runtime change.
- **retriva-crm-assistant** — NOT modified. ADR-026 (ConfirmationReadyOutcome) is accepted at
  C0-A/C0; the bare-affirmative activation path (deployed item 30) is exercised against the
  already-accepted contract, not changed.
- **retriva-webui** — NOT modified. Public chat contract unchanged (constitution §10/§12).

**Branch:** a new branch `phase_g_active` branched from the accepted tip `4336588`
(`phase_f_evaluation`). No accepted commit is amended, squashed, rebased, merged, or pushed.

---

## 3. Starting commits and clean-state verification

- **Starting commit:** `4336588` (HEAD of `phase_f_evaluation`; the accepted Phase F-M commit).
  Reachable from the accepted Gate F-Q lineage `19f784b`, `377cfde`, `ddc7697`, `b52e0c4`,
  `f9210ab`, `4336588`.
- **Clean-state verification before any Phase G work begins (all pre-conditions already met
  by accepted gates; re-confirmed at entry):**
  1. `git status --short` is empty on `phase_f_evaluation` at `4336588`; the new branch
     `phase_g_active` starts clean.
  2. Canonical Gateway suite re-confirmed on the accepted environment
     (`/tmp/kilo/.venv_test_gateway`, `PYTHONPATH` = gateway/src + core/src + crm-assistant/src):
     `python -m pytest tests/ -q -p no:cacheprovider` ⇒ **700 collected / 697 passed /
     3 failed / 0 skipped**, identical failing nodes to the accepted Gate F baseline (the
     three accepted baseline failures only).
  3. `git diff --check 4336588..HEAD` clean; no routing-policy/runtime file changed by Phase G.
  4. No new failure attributable to Phase G in either the canonical suite or the evaluator
     suite (controlled-baseline policy, §40/§34 of plan and constitution §40).

---

## 4. Exact files expected to change

Phase G is activation + deployed acceptance + documentation; it is **additive and config-only**
for behavior:

- `retriva-local-containerized-deployment/.env` (and/or `.env.cust_0007` for the isolated
  tenant) — set `INTENT_CLASSIFIER_ENABLED=true`, `AGENT_INTENT_CLASSIFIER_ENABLED=true`,
  `AGENT_INTENT_ROUTER_MODE=active` (or `shadow` first, then `active`), provider/model/EU/ZDR
  flags, and secret references (`INTENT_CLASSIFIER_OPENROUTER_API_KEY`,
  `INTENT_CLASSIFIER_API_KEY`, `INTENT_CLASSIFIER_SERVICE_AUTH_TOKEN`). **No secret values are
  committed** (constitution §34); only references / deployment-provided secret injection.
- `retriva-local-containerized-deployment/docker-compose.yml` — only if a verified wiring gap
  is found during entry review (currently already wires the classifier block); any change is
  documented and reviewed. Default expectation: **no change**.
- `retriva-gateway/specs/001-hybrid-intent-routing/tasks.md` — Phase G checkboxes completed as
  the walkthrough lands (documentation only; no normative change).
- `retriva-gateway/docs/hybrid-intent-routing.md` + `retriva-gateway/docs/hybrid-intent-
  routing-delivery.md` — delivery report (deployed acceptance evidence, provider/model/region/
  calls/latency/cost as safe bounded metadata, no confidential utterances).
- `retriva-gateway/specs/001-hybrid-intent-routing/CLOSURE.md` (or milestone record) — Gate G
  closure record, written **after** the gate passes (separate commit from the enablement
  commit).

Untouched by Phase G (explicitly preserved): every `retriva_gateway/core/routing/*` module,
`api/v2/chat.py`, `api/internal_routing.py`, the closed `BYPASS_REASON_VALUES` vocabulary,
`dataset-v1.2.jsonl` + schema, `gate-f-thresholds-v1.json`, Core classifier transport source,
CRM Assistant files, and every accepted specification/ADR text except the Phase G progress
rows and the post-gate closure record.

---

## 5. Deployment topology

```
WebUI / clients
   │  POST /gateway/chat | /api/v2/chat   (contract unchanged)
   ▼
Gateway  [control plane]  AGENT_INTENT_ROUTER_MODE = active (isolated tenant)
   ├─ RoutingPipeline (accepted B–F): deterministic → guard → (AMBIGUOUS ⇒ classifier)
   ├─ workflow-context + pending-confirmation registry (in-process, single replica)
   └─ internal GET /internal/routing/status (auth-protected, content-free)
        │  dedicated transport, service credential + purpose marker, correlation id
        ▼
Core  [data plane]  INTENT_CLASSIFIER_ENABLED = true
   └─ POST /v1/intent/classification (internal service network, NOT published by default)
        └─ provider-neutral EU classifier (OpenRouter EU | Bedrock eu-central-1)
```

- WebUI talks only to Gateway (constitution §9). Core is the only component that talks to the
  model provider (architecture §Gateway/Core responsibility split; ADR-0002 Option C rejection).
- The classification endpoint is bound to Core's internal service network; the default
  deployment does not publish it to the host (spec C6/architecture §6b). Publishing it is a
  security-relevant deployment decision documented per constitution §41 and requires a typed
  OpenAPI contract — **out of scope for Phase G** (Phase G keeps it internal-only).
- The Gateway never proxies the endpoint publicly; browser access is rejected (service auth,
  `application/json` only, no CORS).

---

## 6. Process and replica assumptions

- Phase G deployed acceptance runs in **one isolated deployment tenant** with **synthetic
  data**; `cust_0007` is not mutated (acceptance.md "Deployed acceptance", plan.md Phase G).
- The Gateway runs as a **single replica** (the workflow-context and pending-confirmation
  registry is in-process, single-process — architecture §4 documented limitation). Phase G
  assumes exactly one Gateway container in the isolated tenant.
- The deployment process is the supported `retriva-local-containerized-deployment`
  (`docker-compose.yml` + `manage.sh`); no custom process is introduced.

---

## 7. Single-process registry limitation

- The in-process registry (`core/routing/context.py`) is keyed `(tenant_id, session_id, kb_id)`,
  TTL-bounded, capacity-bounded, with deterministic eviction (expired-first purge; typed
  fail-closed rejection at capacity; live confirmations/contexts never silently evicted; no
  spill into an unapproved persistent store — spec C4/architecture §4).
- Phase G therefore exercises cross-turn follow-ups and bare-affirmative activation **only
  within a single Gateway replica**. Horizontal scaling of the Gateway during `active` is
  explicitly **out of scope**; if a future deployment requires >1 replica, it MUST keep mode
  `off` or adopt a governed multi-instance registry change (not this phase). This limitation is
  recorded in the delivery report.

---

## 8. Multi-instance safety behavior

- With a single replica (Phase G assumption): follow-up/confirmation state is correct and
  content-free; safety zeros hold.
- If the deployment inadvertently runs >1 Gateway replica while mode ≠ `off`: registry state is
  not shared → cross-turn follow-ups and pending confirmations may be invisible to the replica
  that receives the follow-up, degrading to clarification/RAG (fail-closed, never a guessed
  mutation). This is the documented degraded UX of architecture §4, not a safety escape.
- Multi-instance correctness is **not** a Phase G acceptance target; the proposal mandates a
  single replica for the deployed walkthrough and records the limitation.

---

## 9. Rollout stages: off → shadow → active

- **off** (default / rollback): legacy router; classifier never called; legacy D1–D5 behavior
  preserved exactly; `INTENT_CLASSIFIER_ENABLED=false`. Entry to a later stage requires explicit
  owner authorization per stage.
- **shadow**: `INTENT_CLASSIFIER_ENABLED=true`, `AGENT_INTENT_ROUTER_MODE=shadow`. New pipeline
  active; classifier invoked only for eligible AMBIGUOUS; recommendations recorded as privacy-
  safe metadata only; route-neutral vs the deterministic-only new pipeline (TR56/TR85). No
  classifier route influence. Used in Phase G as the **pre-active verification stage** before
  promoting to `active`.
- **active**: `AGENT_INTENT_ROUTER_MODE=active`. Retains `shadow` behavior and adds the narrowly
  accepted ambiguity-only classifier influence (TR29–TR31). Every prohibition of TR32–TR39
  still holds.

---

## 10. Entry and exit criteria for every stage

- **Enter `shadow`** when: classifier enabled; EU-residency + ZDR flags enforced; service auth
  token set; strict startup validation passes (or degraded status recorded); readiness shows a
  `classifier` section; the isolated tenant is provisioned with synthetic data.
- **Exit `shadow` → `active`** when: shadow telemetry shows route-neutrality 100% (deployed item
  19), shadow records contain only allowlisted safe fields (item 32), safety zeros hold, and the
  owner reviews the shadow evidence and authorizes `active` (narrowed authority).
- **Enter `active`** when: owner authorization granted (this Gate G entry, contingent on the
  live + paid-provider authorization in §38–§39); deployed acceptance items 1–25 + revision-2
  26–34 pass.
- **Exit `active` → Gate G pass** when: full deployed checklist passes, rollback proven on the
  instance, delivery report + closure record written, and the owner accepts Gate G.

---

## 11. Rollback criteria and procedure

- **Trigger:** any safety-zero violation, regional rejection, content-leakage signal,
  classifier-induced route divergence beyond the accepted ambiguity scope, or owner decision.
- **Procedure:** set `AGENT_INTENT_ROUTER_MODE=off` (optionally also
  `INTENT_CLASSIFIER_ENABLED=false`) in the deployment `.env` and redeploy/restart the Gateway.
  This restores the legacy router and legacy externally observable behavior exactly (TR84/TR87):
  legacy regex routing (including D2/D3 over-match), legacy SSE streaming passthrough (D4), and
  the exact legacy qualification-specific 503 body (D5). The classifier is never called.
- Rollback does **not** reactivate client opt-in or arbitrary workflow selection. Rollback is
  proven on the deployed instance as a Gate G exit criterion (plan.md Gate G: "rollback switch
  proven").

---

## 12. Provider and model selection for the target deployment

- Provider is chosen by the owner from the accepted provider-neutral set: **OpenRouter EU**
  (`INTENT_CLASSIFIER_OPENROUTER_BASE_URL=https://eu.openrouter.ai/api/v1`) or **Bedrock**
  (`INTENT_CLASSIFIER_AWS_REGION=eu-central-1`, `INTENT_CLASSIFIER_BEDROCK_INFERENCE_GEOGRAPHY=eu`).
- Model is a deployment-global validated configuration (`INTENT_CLASSIFIER_MODEL`); selected by
  config only, never from message content, metadata, KB selection, or classifier output
  (constitution §11; spec C7). Threshold invariance holds (no per-tenant/user/KB/model-selected
  thresholds).
- **Exactly one** classifier provider is enabled for the isolated tenant; no fallback provider
  (§31). Phase G does not change the provider/model selection mechanism — only its deployment
  values.

---

## 13. EU-residency verification

- `INTENT_CLASSIFIER_REQUIRE_EU_RESIDENCY=true` (compose default `true`).
- OpenRouter path: base URL is the configured EU endpoint; overrides rejected (architecture §6:
  "OpenRouter path: base URL must be the configured EU endpoint when enforcement is on;
  overrides rejected").
- Bedrock path: region enforced at client construction and call time; regional violation → typed
  error.
- Verified at entry by a startup config assertion and at runtime by `regional_policy_rejection_total`
  monitoring (§28). Any regional rejection is investigated (never silently rerouted).

---

## 14. ZDR verification

- `INTENT_CLASSIFIER_REQUIRE_ZDR=true`, `INTENT_CLASSIFIER_OPENROUTER_ZDR=true`,
  `INTENT_CLASSIFIER_OPENROUTER_DATA_COLLECTION=deny`, `INTENT_CLASSIFIER_OPENROUTER_REQUIRE_PARAMETERS=true`
  (compose defaults already `true`).
- **Required correction/validation:** `INTENT_CLASSIFIER_OPENROUTER_ALLOW_FALLBACKS` MUST be set
  to `false` in the Phase G deployment `.env` (the compose default is currently `true`; with EU
  residency required, fallbacks to a non-EU endpoint MUST be disabled to honor §31 "Failure of an
  allowed regional route MUST NOT trigger fallback to a disallowed endpoint"). This is a
  deployment-config verification item, not a code change.
- ZDR/zero-data-retention is confirmed via the provider contract and the config flags; no
  provider-retained message content is permitted (constitution §29/§33).

---

## 15. Credential and secret provisioning

- Secrets are references only (constitution §34): `INTENT_CLASSIFIER_OPENROUTER_API_KEY`
  (Gateway/Core OpenRouter credential reference), `INTENT_CLASSIFIER_API_KEY` (Core transport
  credential reference), `INTENT_CLASSIFIER_SERVICE_AUTH_TOKEN` (Core internal service credential
  reference). No secret value is committed, logged, metered, or surfaced in status/health.
- Provisioning is via the deployment secret mechanism (env / mounted secret file / secret
  backend); the Phase G enablement commit references the variables but injects no values.

---

## 16. Internal service-token provisioning and rotation

- `INTENT_CLASSIFIER_SERVICE_AUTH_TOKEN` is the internal service credential required by C6;
  the Gateway presents it on every `POST /v1/intent/classification` call (service-to-service
  auth; missing/wrong → 401/403 typed rejection).
- **Rotation:** via environment restart of the Core transport (architecture §9 lifecycle:
  "credential rotation via environment restart of the transport (same as accepted provider
  components)"). Rotation procedure is documented in the delivery report; no code change. Old
  and new tokens are swapped during a maintenance window; both Gateway and Core read the updated
  reference from the deployment secret store.

---

## 17. Core/Gateway endpoint connectivity

- Gateway → Core `POST /v1/intent/classification` via the dedicated Core client (trusted
  headers, internal service credential, purpose marker `X-Retriva-Internal-Purpose:
  intent-classification`, correlation ID). Never `/v1/chat/completions`; never the agent loop or
  RAG.
- Connectivity verified at entry by an internal health/probe call (not a public route) and by
  the deployed acceptance walkthrough (items 3, 17–19). No public Gateway path reaches the
  endpoint; browser access rejected (C6).

---

## 18. Network trust boundary

- Internal service network only; not published by default (C6/architecture §6b).
- Request-size limit (`INTENT_CLASSIFIER_MAX_REQUEST_BYTES=32768` → typed over-limit error),
  input-chars (`INTENT_CLASSIFIER_MAX_INPUT_CHARS=2000`, deterministic truncation), context turns
  (4), timeout (10 s), retries (≤2), concurrency semaphore (8 → typed busy error), per-caller
  rate limit (120/min → typed 429). Cooperative cancellation. Content-free logging.
- Publishing the internal port is a security-relevant deployment decision documented per
  constitution §41 — **out of scope for Phase G** (kept internal).

---

## 19. Health and readiness behavior

- The classifier is an optional capability (constitution §18): its absence/disablement never
  blocks Core readiness. Strict startup validation fails fast when
  `INTENT_CLASSIFIER_STRICT_STARTUP_VALIDATION=true` and config is invalid; otherwise Core marks
  a degraded `classifier` section in the internal status surface and remains ready.
- Gateway readiness is independent of the classifier; mode `off`/disabled preserves legacy
  behavior exactly.

---

## 20. Classifier-disabled startup behavior

- `INTENT_CLASSIFIER_ENABLED=false` (or mode `off`) ⇒ the new pipeline's classifier branch is
  not taken; AMBIGUOUS routes use deterministic fallback (RAG for informational, CLARIFY for
  workflow-adjacent); no classifier call; legacy behavior preserved in `off`. This is the
  rollback/disablement invariant (architecture §7 policy table; TR84/TR87).

---

## 21. Classifier-enabled degraded behavior

- Invalid config with strict validation off ⇒ degraded `classifier` status section; routing
  continues deterministically; classifier failures degrade to clarification/RAG per the decision
  table (architecture §7; TR79). No other model is implicitly invoked (TR21/TR76–TR78): no chat
  model, RAG model, visual model, reranker, alternate provider, or global/lower-security
  endpoint.

---

## 22. Operational metrics

- Content-free counters (architecture §10 / metrics.py): `routing_decision_total{route,source}`,
  `deterministic_match_total{intent}`, `classifier_call_total{provider,outcome}`,
  `classifier_failure_total{category}`, `classifier_latency`, `clarification_total{reason}`,
  `explicit_intent_rejection_total{operation}`, `workflow_route_total{family}`,
  `rag_route_total`, `classifier_bypass_total{reason}`, `regional_policy_rejection_total`.
- Low-cardinality, content-free labels (no message, tenant, user, session, resource, file, raw
  error, unbounded confidence). Fingerprint includes provider/model/base URL/region class/
  prompt version/timeouts — **never secrets** (constitution §34).

---

## 23. Routing-status access control

- `GET /internal/routing/status` is auth-protected, listed in exempt paths only if the
  deployment opts in (architecture §10). Exposes only: enabled mode, canonical provider/model
  (config echo), regional enforcement, allowed region class, last safe failure category,
  bounded counters. No prompts, messages, credentials, stack traces, or raw provider exceptions
  (constitution §41). Publishing it externally requires a typed contract + OpenAPI first — out
  of scope.

---

## 24. Shadow-duration requirement

- Phase G runs a **`shadow` stage** in the isolated tenant for a minimum owner-approved duration
  over representative synthetic EN/IT traffic before promoting to `active`. The exact duration is
  set by the owner at entry authorization (proposal suggests: until the minimum shadow sample
  size in §25 is reached, bounded by a calendar window). Shadow telemetry is ephemeral/bounded
  (§33).

---

## 25. Minimum shadow sample size

- Owner-approved minimum count of eligible ambiguous messages observed in `shadow` with
  route-neutrality verified (proposal suggests a representative sample covering each ambiguous
  family in both EN and IT, including the multi-intent and bare-affirmative controls). The exact
  number is an owner decision at entry; it MUST be large enough to assert 100% route-neutrality
  (deployed item 19) with confidence. Below the minimum, promotion to `active` is blocked.

---

## 26. Shadow route-neutrality acceptance

- Over the shadow sample, the realized route is **100% identical** to the deterministic-only new
  pipeline route (TR56/TR85; acceptance.md "Shadow acceptance"). Classifier recommendations have
  no route effect. A deterministic-vs-classifier-vs-expected comparison table is delivered. Any
  divergence beyond the accepted ambiguity scope fails the shadow exit criterion.

---

## 27. Safety-zero monitoring

- Continuously asserted under live operation: mutation-intent false-positive = 0; multi-intent
  consequential-execution = 0; cross-tenant context acceptance = 0; classifier-driven
  authorization = 0; disallowed-region fallback = 0; content leakage = 0. Any nonzero value
  pages and triggers rollback (§11).

---

## 28. Classifier timeout and failure monitoring

- `classifier_failure_total{category}` (incl. `classifier_timeout`, `classifier_unavailable`,
  `classifier_invalid_output`, `regional_policy_rejected`) and `classifier_latency` are observed.
  On failure, the Gateway applies the deterministic fallback (clarify/RAG; never a disallowed
  provider; never another model implicitly — TR21/TR75–TR80). Alert on failure-rate threshold
  breach (§30).

---

## 29. Regional-policy rejection monitoring

- `regional_policy_rejection_total` is monitored (spec C6/architecture §10). Any rejection
  indicates misconfiguration or an attempted out-of-region call; it is investigated and MUST NOT
  be silently rerouted (constitution §31). A rejection is a typed error, never a fallback.

---

## 30. Alert thresholds

- Owner-defined at entry; proposal defaults: (a) **any** safety-zero violation → immediate page +
  rollback; (b) `regional_policy_rejection_total` > 0 → investigate within SLA; (c)
  `classifier_failure_total` rate > agreed bound (e.g. sustained > 5%) → warn + review;
  (d) `classifier_latency` p95 > agreed bound → warn; (e) shadow route-neutrality < 100% → block
  promotion. Thresholds are deployment configuration, not code.

---

## 31. Incident response

- Classifier failure/timeout → deterministic fallback (safe), no implicit other model (§21/§28).
- Regional rejection → typed error, no fallback, investigate (§29).
- Content-leakage detection (any raw message/prompt/identifier in logs/metrics/status) → stop the
  instance, revoke the exposure, audit, and report per the production privacy policy (§32/§33).
- Safety-zero breach → immediate rollback to `off` (§11).
- All incidents follow the append-oriented audit trail (constitution §30).

---

## 32. Production privacy policy

- No raw messages, prompts, full classifier responses, history, tool arguments, company names,
  customer codes, tenant/user/session IDs, resource IDs, business identifiers, ACP payloads,
  import contents, campaign members, or qualification evidence enter logs/metrics/status/shadow
  (TR51–TR58; constitution §29/§33). Shadow records use only the spec §Shadow-mode privacy
  allowlist (schema version, prompt version, provider/config fingerprint, deterministic/classifier
  route category, workflow family, interaction mode, explicitness class, agree/disagree,
  confidence bucket, safe reason codes, latency, aggregated token/cost counters, regional-policy
  result, safe error category, timestamp, deployment mode).

---

## 33. Log and metric retention

- Default: aggregate counters + bounded ephemeral in-process diagnostics (ring buffer, TTL 15 min,
  capacity 1000, lost on restart) — architecture §10. No persistent message-level corpus.
- Retention of aggregate metrics follows the deployment's bounded, access-controlled policy; no
  content is retained. Per-message persistence of any kind requires the separately approved
  privacy-safe sampling process (synthetic or explicitly authorized content, documented
  retention, access control, minimization, deletion, audit) — **not part of Phase G**.

---

## 34. No raw-message shadow corpus

- The shadow stage records only allowlisted aggregate/safe fields (§32). A raw-message shadow
  corpus is explicitly out of scope; offline review of actual messages requires the separately
  approved privacy-safe sampling process. Phase G shadow evidence contains no message content.

---

## 35. Change-management procedure

- Phase G is a documented deployment change: the enablement `.env` diff is reviewed and committed
  on `phase_g_active`; the compose wiring is reviewed; any internal-port publishing decision is
  documented per constitution §41 (not taken in Phase G). Delivery docs are committed separately.
  Each commit is independently reviewable (§45). No accepted runtime/dataset/threshold/ADR is
  modified.

---

## 36. Release and rollback artifacts

- **Enablement artifacts:** `retriva-local-containerized-deployment/.env` (mode + classifier +
  creds refs) and the reviewed `docker-compose.yml` (if changed).
- **Rollback artifact:** the prior `.env` (mode `off`, classifier disabled) — redeploy restores
  legacy behavior exactly (TR84/TR87).
- **Evidence artifacts:** `docs/hybrid-intent-routing-delivery.md` (deployed checklist 1–34,
  provider/model/region/calls/latency/cost as safe metadata), `CLOSURE.md` Gate G record.
- Merge/release are **not** produced by Phase G (§42).

---

## 37. Compatibility with accepted baseline failures

- The full Gateway suite remains **700 collected / 697 passed / 3 failed / 0 skipped** (the three
  accepted baseline failures: `test_kbs_list_translates_core_response_to_webui_shape`,
  `test_speech_placeholder`, `test_assertions`). Phase G adds **zero** new failures and changes
  **zero** baseline failures (controlled-baseline policy). The suite MUST NOT be described as
  passing while the exit code is nonzero (Gate F acceptance carry-over). Deployed acceptance is
  operational and separate from the unit suite.

---

## 38. Live smoke-test authorization boundary

- The authorized live smoke test is exactly the **deployed acceptance walkthrough** (acceptance.md
  items 1–34) executed in the isolated tenant on synthetic data, `cust_0007` untouched. It is the
  only live run authorized by Gate G entry. No other live testing (e.g. against production
  tenants, real customer data, or extended scenarios) is authorized without separate owner
  authorization.

---

## 39. Paid-provider authorization boundary

- Phase G's live classifier invocation is a **paid-provider** call (OpenRouter/Bedrock). Gate F
  explicitly did **not** authorize live or paid-provider use ("Provider-specific live quality is
  not established by Gate F. A live-provider evaluation requires separate authorization.").
- **Gate G entry authorization MUST explicitly grant live + paid-provider use for the isolated
  deployment tenant only**, scoped to the single chosen classifier provider, synthetic data,
  cost-bounded, EU-residency + ZDR enforced. No other paid provider, no production-wide paid
  use, and no paid use beyond the classifier is authorized by this phase.

---

## 40. Deployment validation

- Container stack up via the supported deployment; Core classifier endpoint reachable on the
  internal network; Gateway `AGENT_INTENT_ROUTER_MODE=active` (after `shadow`); deployed checklist
  items 1–34 executed and passing; rollback switch proven on the instance; safety zeros hold;
  status endpoint content-free and auth-protected. Validated in the isolated tenant only.

---

## 41. Production activation decision

- The owner decides production activation **after** the `shadow` evidence (route-neutrality 100%,
  allowlist-only records) and the `active` deployed walkthrough pass, and after reviewing the
  delivery report. Phase G entry does **not** itself authorize production-wide activation; it
  authorizes the isolated-tenant active enablement + acceptance. Production activation is a
  separate owner decision (and may require its own governance if it leaves the isolated tenant).

---

## 42. Merge and release authorization boundaries

- Phase G entry authorizes branch-local, reviewable commits on `phase_g_active`. It authorizes
  **no merge into `main`/trunk, no release/tag, no deployment to production tenants beyond the
  isolated one, and no publish of the internal endpoint**. Merge/release require separate explicit
  owner authorization after Gate G passes.

---

## 43. GF-001 disposition

- **Unchanged and non-blocking.** GF-001 (dangling reranker ADR reference,
  `retriva-core/docs/governance/GF-001-dangling-reranker-adr-reference.md`) remains OPEN and out
  of Phase G scope. Phase G does not amend the constitution, does not expand ADR-0002 to govern
  reranking, and changes no reranker behavior. The Hybrid Intent Routing classifier uses the
  accepted `INTENT_CLASSIFIER_*` domain, independent of the reranker reference.

---

## 44. Explicit exclusions

Phase G explicitly does **not**:

- modify runtime source in retriva-gateway or retriva-core (behavior is carried forward from
  accepted Gates B–F);
- modify the dataset, dataset schema, or `gate-f-thresholds-v1.json`;
- modify the consequential-candidate contract or the closed `BYPASS_REASON_VALUES` vocabulary;
- change provider/model selection mechanism (only deployment config values);
- enable consequential active authority (TR32–TR39 still hold; the guard is the only path);
- invoke the classifier on streaming (architecture §7.3; spec §Streaming policy);
- create a persistent classifier cache or persistent confirmation store beyond the accepted
  in-process registry;
- implement multi-instance registry synchronization (single replica required);
- resolve GF-001;
- merge, release, or deploy beyond the isolated tenant;
- correct the three accepted baseline defects;
- publish the internal classification endpoint.

---

## 45. Git checkpoint and commit-separation strategy

- Branch `phase_g_active` from `4336588`; no accepted commit touched.
- Checkpoint commits, each independently reviewable:
  1. Deployment enablement: `.env` (mode `active`/after `shadow`, classifier enabled, EU/ZDR
     flags, `ALLOW_FALLBACKS=false`, secret **references** only) ± reviewed `docker-compose.yml`
     if a gap is found. **Created only after Gate G entry authorization, including the live +
     paid-provider authorization (§38–§39).**
  2. Delivery report: `docs/hybrid-intent-routing.md` + `-delivery.md` (deployed evidence).
  3. `tasks.md` Phase G progress rows; `CLOSURE.md` Gate G record — **only after the gate passes**.
- Strict separation guarantees the accepted runtime/dataset/thresholds/ADRs stay untouched;
  review focuses on deployment config + evidence docs.

---

## 46. Risks, blockers, and owner decisions

- **Prerequisites:** accepted Gates B, C0-A, C0, C, D, E, F are the Phase G entry prerequisites
  and are accepted (per the Gate F acceptance record). No prerequisite is unmet.
- **Owner decision — live + paid provider (§38–§39):** Gate G entry MUST explicitly authorize
  live EU classifier invocation and paid-provider use for the isolated tenant. This is the single
  hard precondition for enabling `active` against a real provider.
- **Owner decision — provider/model (§12):** select OpenRouter EU or Bedrock `eu-central-1` and
  the model; config-only.
- **Risk — ZDR fallback (§14):** compose default `INTENT_CLASSIFIER_OPENROUTER_ALLOW_FALLBACKS=true`
  MUST be set `false` for the Phase G deployment; verified at entry. Mitigated by config review.
- **Risk — confirmation-safe tenant (ADR-026 §5):** if the bare-affirmative activation walkthrough
  (item 30) is exercised, the tenant MUST configure `approved_store_tenant` (a deployment lacking
  it is "not confirmation-safe"). Verified or the item is scoped out of the walkthrough.
- **Risk — single-replica (§6–§8):** the registry is in-process; Phase G runs one Gateway replica.
  Horizontal scaling during `active` is out of scope and would degrade follow-ups fail-closed.
- **Risk — baseline failures (§37):** the three accepted baseline failures remain; Phase G adds
  none. Recorded, not fixed.
- **GF-001:** unchanged, out of scope (§43).
- **Blockers:** none that prevent preparing this proposal; the only gating item is the owner's
  explicit live + paid-provider authorization, which is itself the entry-decision content.

---

## 47. Verdict

**READY FOR PHASE G ENTRY AUTHORIZATION.**

All entry prerequisites (accepted Gates B, C0-A, C0, C, D, E, F), the normative sources (Spec 001
pack revision 2, ADR-0002, ADR-026, the constitution v1.1), and the Gate G criteria are defined
and derivable. The proposal scopes Phase G strictly to: enabling `active` (after a `shadow`
verification stage) in an isolated synthetic tenant; running the owner-reviewed deployed acceptance
walkthrough (items 1–34); proving the rollback switch; and writing the delivery/closure records —
with explicit exclusions for runtime/dataset/threshold/ADR changes, multi-instance registry sync,
GF-001 resolution, merge/release, and production-wide activation. The system under test is the
accepted B–F pipeline, unchanged.

Entry authorization is contingent on the owner explicitly granting the two decisions recorded in
§46: (1) **live EU classifier invocation + paid-provider use for the isolated tenant only**, and
(2) **provider/model selection** (OpenRouter EU or Bedrock `eu-central-1`). With those granted,
Phase G may proceed on branch `phase_g_active` from `4336588` under the commit-separation strategy
of §45, on the baseline-relative, zero-regression basis (700/697/3/0, three failures unchanged).

---

## Formal closure handoff

Gate B, Gate C0-A, Gate C0, Gate C, Gate D, Gate E, and Gate F are accepted. Phase G remains
unapproved until this entry proposal is authorized and its gate passes. This proposal establishes
and proposes the Phase G scope: the accepted hybrid pipeline is enabled in `active` (limited to
ambiguous informational + safe-proposal influence per TR29–TR31) in an isolated synthetic tenant
after a route-neutral `shadow` stage; the deployed acceptance walkthrough (acceptance.md items
1–34) is executed against a live EU, ZDR-enforced, provider-neutral classifier; the rollback
switch is proven; and the delivery/closure records are written. It does not authorize runtime
source changes, dataset or threshold changes, consequential active authority, streaming classifier
invocation, persistent classifier/confirmation storage beyond the accepted in-process registry,
multi-instance synchronization, GF-001 resolution, merge, release, production-wide activation, or
paid-provider use beyond the single isolated-tenant classifier authorized at entry.
