# Feature Spec — Hybrid Intent Routing for Retriva Chat (v1, revision 2)

Spec pack: `001-hybrid-intent-routing`
Status: ACCEPTED (revision 2) — Owner Acceptance Gate A approved 2026-10-01
(including the Constitution §11 interpretation, the activation model, and
the narrowed ACTIVE-mode authority); implementation proceeds only through
the accepted plan.md phase gates.
Revision 2 date: 2026-10-01
Governing ADR: ADR-0002 (`docs/adr/0002-hybrid-intent-routing.md`)
Constitution (highest authority): `retriva-core/.agent/rules/retriva-constitution.md`
v1.1, referenced here and in ADR-0002.
Extends: Gateway ADR-0001 (extension tools for the chat agent loop); CRM
Spec 020 / ADR-023 (accepted chat-tool surface and stage-separation policy);
CRM Spec 021 / ADR-024 (evidence enrichment tools). Supersedes, for chat
workflow routing only, the unaccepted `docs/sdd/SDD-Retriva-Gateway-Granular-
Intent-Detection.md` (its catalog-intent design was never accepted and its
non-workflow intents are production-dead). Changes no accepted public chat
API contract except the narrow streaming behavior listed in §Scope.
Governance follow-up recorded (outside this pack's scope): **GF-001** —
constitution §11 cites a governing reranker ADR that does not exist;
recorded at `retriva-core/docs/governance/GF-001-dangling-reranker-adr-reference.md`.

## Revision 2 summary (owner review "accept with changes")

Revision 2 applies the owner's required revisions without changing the
accepted architectural principle or any previously accepted decision listed
in §Accepted decisions. It adds or corrects:

1. an explicit Constitution §11 compatibility analysis separating workflow
   dispatch from provider/model routing (§Constitution §11 compatibility);
2. a full trust boundary for the Core classification endpoint (contract C6);
3. the Gateway/Core responsibility split with ownership invariants
   (§Gateway/Core responsibility split);
4. a no-recursion invariant for classifier calls (§No-recursion invariant);
5. a finalized streaming policy, including the typed
   `workflow_stream_unsupported` body and the chosen ambiguous-streaming
   policy (§Streaming policy, contract C5);
6. narrowed ACTIVE-mode classifier authority, stated in this spec,
   architecture.md, acceptance.md, plan.md, tasks.md, and ADR-0002
   (§Active-mode classifier authority);
7. a confidence policy with validated bounds, threshold semantics, and
   malformed/conflicting-input behavior (contract C7, §Confidence policy);
8. a privacy-safe shadow-mode record specification (§Shadow-mode privacy);
9. classifier failure behavior with an explicit no-implicit-model-invocation
   rule (§Classifier failure behavior);
10. a deterministic multi-intent policy (§Multi-intent policy);
11. the full typed pending-confirmation binding (contract C4,
    §Pending confirmation state);
12. the governing invariant (§Governing invariant);
13. the reranker governance defect recorded separately as GF-001 (not fixed
    here, not governed by ADR-0002);
14. revised test and acceptance requirements mapped to the review's required
    proof list (acceptance.md TR matrix; plan/tasks updated).

## Goal

Preserve the deterministic safety boundary of chat routing — accepted
Company Intelligence workflow intents route to the bounded agent loop, all
other messages stay on grounded, cited RAG — and add a provider-neutral LLM
intent classifier that is invoked **only** for messages the deterministic
router cannot classify confidently. The classifier improves natural-language
understanding, multilingual (EN/IT) coverage, and ambiguous follow-up
handling. It is an untrusted semantic recommender only: it never receives,
returns, or overrides permissions, never authorizes a consequential business
mutation, and never bypasses EU/regional policy.

Architectural principle: **LLM for ambiguous language understanding;
deterministic code for authority, state transitions, and consequences.**

## Accepted decisions (unchanged by revision 2)

Deterministic routing remains first; the LLM classifier is invoked only
after a deterministic AMBIGUOUS result; the classifier is disabled by
default; rollout progresses through OFF, SHADOW, and ACTIVE modes;
classifier transport is provider-neutral; classifier configuration is
distinct from visual and rerank model configuration; EU or otherwise
approved regional processing is enforced; no fallback to a disallowed global
endpoint is permitted; classifier output is a recommendation, not authority;
clear requests never need a classifier call; every consequential action
retains deterministic explicit-intent guards; the evaluation dataset includes
English and Italian; ordinary CI uses deterministic fake classifier
responses; acceptance uses an isolated tenant and does not mutate cust_0007;
streaming executes no business tools in this milestone.

## Current state (verified, code as evidence)

- `retriva_gateway/core/intent.py` is the only production router. The chat
  endpoint (`api/v2/chat.py:52-60`) calls `IntentDetector.is_crm_workflow()`
  for non-streaming requests; a single multi-alternative regex
  (`intent.py:75-93`) matches workflow families:
  - ACP/cohort (propose/review/approve/activate/rollback/generate/rebuild +
    ACP/cohort nouns), qualification (`qualify|qualification` +
    candidates/workbook/job), enrichment (`enrich*|accept` + customers/
    evidence/... or `enrich*` + pronoun), company import
    (`analyz*|commit|reject` + import/batch/workbook), campaigns
    (`campaign` + audience/create/approve/commit/outcome/history/addressed;
    `import` + campaign/company history).
- Routing to the agent requires no client opt-in (asserted by
  `tests/test_acp_chat_policy.py::test_workflow_intent_routes_to_agent_loop_without_optin`).
  Explicit opt-in (`tools_enabled` + `session_id`) forces agent mode for any
  non-streaming message. `AGENT_TOOLS_ENABLED=false` forces plain RAG for
  everything (master switch, `config.py:91`).
- Streaming requests **never** enter the agent loop: opt-in falls back with a
  warning (`chat.py:47-50`) and the intent branch is gated on
  `not request.stream` (`chat.py:52`). Streaming is a raw SSE passthrough of
  Core grounded-QA (`core/client.py:85-94`, `chat.py:188-190`).
- The richer `analyze()` classifier (catalog/metadata intents) and the
  workflow-stickiness registry are **production-dead**: `_mark_sticky` is only
  reachable from `analyze()` (`intent.py:210-211`) while the router calls
  `is_crm_workflow()` (`intent.py:226-227`), which can never arm stickiness.
  Cross-turn confirmations ("yes, enrich them") therefore work only when they
  contain a matched verb+noun pair; bare "yes" routes to RAG.
- Normalization is case-insensitivity only. There is no negation handling, no
  hypothetical-language handling, no quoted-text/code-block handling, and the
  `_KNOWLEDGE_FRAMING` veto (`intent.py:99-104`) applies only to sticky
  continuation, never to direct regex matches — "How do I activate an ACP?"
  routes to the agent loop today.
- Known over-match (deploy-safety review): the `enrich\w*` + broad-noun
  alternatives (`intent.py:84-87`) can route ordinary RAG questions that
  merely mention "enriching customers/evidence" into the agent loop.
- Typed workflow errors never fall back to RAG (by explicit design:
  `tools.py:1873-1874`, `loop.py:97-98, 212-219`; asserted by
  `tests/test_chat_qualification_policy.py:163-169`,
  `tests/test_acp_chat_policy.py:207-227`).
- Authorization is enforced at the tool boundary, not by routing: trusted
  principal (client `X-Retriva-User` stripped, `core/client.py:32-58`),
  session/KB/attachment trusted context, opaque-ID validation
  (`tools.py:1912-1927`), server-side permission and lifecycle checks in the
  CRM extension (`ADR-023` decision 2-4). Body `actor_id`s
  (`chat:{session_id}`) are attribution-only.
- The Gateway has no metrics library (loguru only) and no strict startup
  validation. The strict-startup + EU-region precedent lives in Core
  reranking (`retriva-core/docs/reranking.md`: strict validation, EU region
  enforcement, no fallback, degraded status).

## Defects recorded (constitution §4: code vs accepted requirements)

1. D1 — Cross-turn workflow continuation is unreachable in production
   (stickiness cannot arm; Spec 021 "review fix 17" intent not realized in
   the live path). Bare confirmations degrade to RAG.
2. D2 — "How do I activate an ACP?" / "Explain campaign audience commit"
   route to the agent loop instead of grounded RAG (documentation framing is
   not vetoed for direct regex matches).
3. D3 — `enrich\w*` + broad-noun alternatives over-match ordinary RAG
   questions into the agent loop.
4. D4 — A streaming request carrying an explicit workflow command silently
   produces a text-only RAG answer that can read as if the workflow ran; no
   typed signal tells the client to use the non-streaming workflow path.
5. D5 — The agent-unavailable 503 body is qualification-specific text for all
   workflow families (`chat.py:97-103`).

The D1-D5 fixes are implemented by the new deterministic routing pipeline
specified below and become externally effective only in modes `shadow` and
`active`. Mode `off` — the default and the rollback state — invokes the
legacy routing path and preserves legacy externally observable behavior,
including the documented D1-D5 defects where those defects exist (see
§Activation model for the normative mode gating and the D5 resolution).

Governance defect recorded separately (outside this pack's implementation
scope): **GF-001** — constitution §11 defines the accepted reranker policy
"as defined by the governing ADR", but no reranker ADR exists. Recorded at
`retriva-core/docs/governance/GF-001-dangling-reranker-adr-reference.md`;
it is not fixed inside ADR-0002, ADR-0002 does not govern reranking, and no
constitution amendment is proposed by this pack.

## Constitution §11 compatibility: workflow dispatch vs provider/model routing

The hybrid classifier touches two distinct decision domains that the
constitution treats differently. They MUST remain separate in every
implementation, test, and document of this pack.

**A. Workflow dispatch (application-level, control plane):** which
already-authorized application workflow handles the current chat turn —

- grounded RAG;
- the bounded Company Intelligence agent loop;
- clarification.

**B. Provider and model routing (transport-level, data plane):** which
provider, model, endpoint, region, residency, retention, and security
posture carry a model call —

- provider selection;
- model selection;
- endpoint selection;
- region and residency selection;
- security posture;
- retention policy.

The hybrid classifier may inspect the current authorized chat request
(message text plus the typed workflow-context summary) to recommend
**workflow dispatch (A) only**. It MUST NOT use message content,
conversation content, selected Knowledge Base, custom metadata, classifier
output, or user instructions to choose provider, model, base URL, endpoint,
region, residency policy, data-retention policy, security mode, or
confidence threshold (domain B).

Normative statement (verbatim, binding on this pack):

> This feature classifies the requested interaction and recommends one of
> the already authorized application workflows. It does not perform
> content-dependent provider or model routing.
>
> The classifier provider, model, endpoint, region, and security policy are
> selected only through validated deployment configuration. User messages,
> conversation content, Knowledge Base selection, custom metadata, and
> classifier output cannot alter those choices.

### Why this is compatible with Constitution §11

1. §11's normative objects are "Providers and models", "Model routing",
   "reranker selection", and "Model failure". It governs **which
   provider/model/endpoint/region handles data**: selection MUST go through
   validated configuration and provider-neutral interfaces, and MUST NOT be
   inferred from arbitrary user content, custom metadata, model-generated
   suggestions, or untrusted request fields. The hybrid design performs no
   such inference: the classifier's provider, model, base URL, endpoint,
   region, security posture, and retention are fixed, deployment-global,
   validated configuration (the same pattern as the accepted reranker
   policy), and no request field, message content, Knowledge Base choice,
   custom metadata, or classifier output can alter them.
2. Application-workflow dispatch is an orchestration decision of the control
   plane (§9: "Gateway is the policy and orchestration choke point … Every
   consequential action MUST be represented by an explicit workflow or
   contract"). It is necessarily content-dependent: the accepted, deployed,
   tested production router already dispatches chat turns on message content
   (`intent.py:75-93`, `chat.py:52-60`; ADR-0001's agent loop exists so
   chat can reach the typed CRM workflows at all). A reading of §11 that
   forbade content-dependent application-workflow dispatch would outlaw this
   accepted behavior and make §6/§9/§30 unsatisfiable, because a system that
   cannot interpret which authorized workflow a request concerns cannot
   route it to that workflow's explicit contract.
3. The classifier's output is a **model-generated suggestion**, and §11
   explicitly forbids inferring model routing from model-generated
   suggestions. The design therefore hard-forbids classifier output (and
   every message/metadata/KB field) from domain B choices; classifier output
   only recommends workflow dispatch, re-validated by deterministic Gateway
   policy (§Governing invariant).
4. No tenant-specific, KB-specific, user-specific, or request-specific
   classifier selection is introduced (mirroring §11's reranker clause and
   the reranking precedent). Introducing per-scope classifier selection in
   the future would require the full §11 process (ADR, security and
   residency analysis, cache-isolation analysis, compatibility assessment,
   deterministic tests, operational acceptance) and is out of scope.
5. Model failure never silently routes confidential data to a provider,
   region, or endpoint disallowed by the active policy (§11 final clause;
   §31): classifier failure is a typed, sanitized error with deterministic
   degradation and no fallback (§Classifier failure behavior).

**Conclusion (explicit, not silent):** these documents conclude that
Constitution §11 forbids content-dependent **provider/model/endpoint/region
selection** and does not forbid content-dependent **application-workflow
dispatch**. No constitution amendment is therefore required for this ADR.
This interpretation is recorded here and in ADR-0002 for owner acceptance;
if the owner rejects it, the fallback required by the constitution (§5) is a
constitution amendment proposal, not a quiet reinterpretation inside the
implementation.

## In scope

1. A typed, versioned routing taxonomy (topic, intent, mode, explicitness,
   confidence, clarification, resource reference, reason codes) with a closed
   JSON schema (§Contracts).
2. A deterministic routing engine replacing the single-regex decision:
   typed rules with priorities and reason codes; negation, hypothetical,
   quoted-text, code-block, pasted-documentation, prompt-writing and
   explain-an-API detectors; EN/IT normalization; typo tolerance where safe;
   explicit-command detection; safe default AMBIGUOUS → clarification/RAG.
3. Deterministic explicit-intent guards for consequential operations
   (approve/commit/activate/supersede/rollback/deactivate/mark-addressed/
   canonical import mutation/merge/exclusion activation/paid-provider
   approval), independent of any classifier output.
4. A typed, session- and tenant-scoped, bounded, expiring workflow-context
   registry (opaque resource references only) that production routing
   actually arms and consults, and that only deterministic tool outcomes or
   deterministic routing may write, including the typed pending-confirmation
   state (contract C4).
5. A provider-neutral classifier interface (`IntentClassifier`,
   `IntentClassification`, `IntentClassificationError`,
   `IntentClassifierConfig`) with strict structured-output validation; the
   Gateway treats results as untrusted recommendations and re-validates every
   field.
6. A dedicated Core classifier transport domain (`INTENT_CLASSIFIER_*`)
   behind an internal Core endpoint with a defined trust boundary
   (contract C6), mirroring the accepted reranking pattern: provider-neutral,
   strict startup validation, EU-region enforcement with no fallback, secrets
   as references, bounded timeout/retries/budgets, service-to-service
   authentication, request/rate/concurrency bounds.
7. Shadow mode (`off|shadow|active` mode switch, default `off`): shadow
   records classifier output as safe structured metadata without the
   recommendation being able to alter the deterministic route (route-neutral
   with respect to classifier recommendations — not necessarily identical to
   legacy routing) (§Shadow-mode privacy, §Activation model); activation to
   `active` is configuration-controlled and reversible (rollback switch =
   set mode `off`, which restores the legacy router).
8. Focused clarification behavior (concise, action-specific, never
   tool-executing), including the streaming typed-error path (§Streaming
   policy).
9. Bounded, content-free routing metrics and a sanitized internal status
   surface.
10. A versioned, privacy-safe, synthetic-only EN/IT evaluation dataset and
    the deterministic test suite (§Acceptance), including adversarial
    prompt-injection cases.
11. Documentation set (§Documentation) and delivery report.

## Out of scope (non-goals)

- No streaming agent protocol (Option B of ADR-0002 §Streaming): no new SSE
  event types, no tool events over streams; deferred to a separately
  governed public API change.
- No classifier invocation for ambiguous **streaming** requests in this
  milestone (policy chosen in §Streaming policy); enabling it later requires
  the constraints recorded there.
- No change to tool registry contents, tool schemas, CRM routes, permission
  vocabulary, tenant semantics, or ACP/import/campaign/qualification
  workflow state machines.
- No classifier authority over consequential mutations; no classifier
  tool-calling; no classifier-selected providers.
- No classifier for every message; no persistent classification cache
  (bounded in-process, privacy-safe keyed cache only if a measured need
  emerges; default none).
- No metadata-derived routing (custom user metadata, KB tags, Qdrant
  payloads remain routing-inert).
- No per-tenant, per-user, per-KB, per-metadata, per-message, or
  model-selected confidence thresholds (§Confidence policy).
- No multi-intent decomposition or partial execution (policy B chosen,
  §Multi-intent policy); safe decomposition (option A) is a possible future
  extension requiring its own acceptance.
- No persistent message-level shadow corpus of any kind (§Shadow-mode
  privacy).
- No retrofit of the production-dead catalog/metadata intents of the
  unaccepted SDD; they remain out of the chat routing pipeline.
- No deletion of `IntentDetector.analyze()` in this pack (deprecation is
  deferred; behavior-preserving).
- No reranking governance change and no constitution amendment: the reranker
  ADR dangling reference is recorded as GF-001 and resolved through its own
  governance process.

## Definitions

- **Consequential operation**: an operation that mutates canonical business
  state or spends paid-provider budget, per CRM ADR-022/023/024 stage
  separation (approve, commit, activate, supersede, rollback, deactivate,
  mark-addressed, canonical import mutation, organization merge, exclusion
  activation, paid-provider authorization).
- **Safe workflow proposal/analysis**: non-mutating workflow operations
  (propose/analyze/status/review-preparation/readiness), which may enter the
  bounded agent loop because the loop itself cannot mutate without further
  deterministic gates.
- **AMBIGUOUS**: the deterministic engine cannot select a route at its
  configured confidence; only this outcome may invoke the classifier.
- **Workflow-adjacent AMBIGUOUS**: AMBIGUOUS with at least one
  workflow-vocabulary signal (family noun or operation verb matched, but no
  rule classified the message). Workflow-adjacent ambiguity clarifies;
  non-adjacent ambiguity (no workflow signal) routes to RAG.
- **MULTI-INTENT**: a message that matches or plausibly contains more than
  one workflow intent (informational + consequential, or several
  consequential operations), including conjunction/sequencing phrasing
  ("and then", "e poi", ";"). Detection is deterministic (rule engine) with
  classifier reason-code support; handling is always clarification
  (§Multi-intent policy).

## Activation model (modes; normative)

The mode switch `AGENT_INTENT_ROUTER_MODE` gates which router executes. It
is the single normative model of activation for every phase, document, and
test of this pack:

1. **`off`** —
   - is the default;
   - invokes the legacy routing path (`IntentDetector.is_crm_workflow()`
     single-regex decision; streaming SSE passthrough);
   - preserves legacy externally observable behavior, including the
     documented D1-D5 defects where those defects exist;
   - does not activate the new deterministic routing fixes, guards,
     clarification policy, multi-intent policy, confidence behavior,
     pending-confirmation state, or classifier (the classifier is never
     called; the workflow-context registry is not armed);
   - permits the new engine's AMBIGUOUS / workflow-adjacency labels to be
     computed for shadow observation only where applicable, never altering
     the returned route;
   - is the rollback state.
2. **`shadow`** —
   - activates the new deterministic routing pipeline and its D1-D5 fixes;
   - applies the new deterministic guards and policies;
   - may invoke the classifier only for eligible deterministic AMBIGUOUS
     outcomes;
   - records the classifier recommendation using the accepted privacy-safe
     telemetry (§Shadow-mode privacy);
   - never allows the classifier recommendation to change the deterministic
     route (route-neutral with respect to classifier recommendations, not
     necessarily identical to legacy routing).
3. **`active`** —
   - retains all deterministic fixes and guards from `shadow`;
   - permits classifier influence only within the narrowly accepted,
     non-consequential ambiguity scope (§Active-mode classifier authority);
   - preserves every prohibition and governing invariant of this pack.

**D5 resolution (normative):** the revised generic (family-neutral)
agent-unavailable HTTP 503 response is part of the new pipeline and is
externally effective only in `shadow` and `active`. No already accepted
requirement mandates the generic text in `off`; therefore `off` preserves
the exact legacy qualification-specific 503 body, so that `off` remains a
genuine behavioral rollback. Streaming behavior is mode-specific per
§Streaming policy: unchanged legacy SSE passthrough in `off`; the C5 typed
409 and neutral-clarification behaviors in `shadow`/`active`.

## Contracts

### C1 — Routing taxonomy (closed, versioned)

Topic: `ACP | QUALIFICATION | COMPANY_IMPORT | CAMPAIGN | DOCUMENTATION |
GENERAL`.

Intent (closed vocabulary, aligned with the accepted tool registry):
`RAG_QUESTION, WORKFLOW_DOCUMENTATION, STATUS_EXPLANATION,
CAPABILITY_QUESTION, ACP_COHORT_PROPOSAL, ACP_COHORT_REVIEW,
ACP_COHORT_APPROVAL, ACP_GENERATION, ACP_REVIEW, ACP_APPROVAL,
ACP_ACTIVATION, ACP_SUPERSESSION, ACP_ROLLBACK, ACP_STATUS, ACP_LINEAGE,
QUALIFICATION_REQUEST, QUALIFICATION_STATUS, QUALIFICATION_REVIEW,
QUALIFICATION_APPROVAL, COMPANY_IMPORT_ANALYSIS, COMPANY_IMPORT_REVIEW,
COMPANY_IMPORT_APPROVAL, COMPANY_IMPORT_COMMIT, COMPANY_IMPORT_STATUS,
CAMPAIGN_CREATE, CAMPAIGN_AUDIENCE_ANALYSIS, CAMPAIGN_AUDIENCE_REVIEW,
CAMPAIGN_AUDIENCE_APPROVAL, CAMPAIGN_AUDIENCE_COMMIT,
CAMPAIGN_HISTORY_IMPORT, CAMPAIGN_MARK_ADDRESSED, CAMPAIGN_OUTCOME_UPDATE,
CAMPAIGN_STATUS, AMBIGUOUS, UNSUPPORTED, CLARIFICATION_REQUIRED`.

Interaction mode: `INFORMATIONAL | ANALYSIS | REVIEW | MUTATION |
DESTRUCTIVE_MUTATION | UNKNOWN`.

Explicitness: `EXPLICIT | IMPLICIT | AMBIGUOUS | NEGATED | HYPOTHETICAL |
QUOTED_EXAMPLE`.

General outcomes: `AMBIGUOUS | UNSUPPORTED | CLARIFICATION_REQUIRED`.

### C2 — Structured classifier contract (schema_version "1")

The classifier returns strict JSON, `additionalProperties: false`, closed
enums, `confidence` bounded [0,1], no chain of thought, no repeated user
content, no tenant/permission/tool-argument/URL/SQL/provider fields, no
mutation-authorization field, no route field, no execution-plan field.
Fields: `schema_version, topic, intent, mode, explicitness, confidence,
requires_clarification, clarification_reason, resource_reference (opaque
string or null), language, reason_codes (bounded closed list)`. Every field
is re-validated deterministically by the Gateway; any violation — including
missing, non-numeric, non-finite, out-of-range, or string-typed confidence,
topic/intent inconsistency, intent/mode disagreement, or reason codes that
conflict with the selected intent — yields a safe classification failure
(clarification), never permissive routing (§Confidence policy).

### C3 — Route decision record (internal)

`route (AGENT_LOOP | RAG | CLARIFY | REFUSE_STREAM | LEGACY_RAG)`,
`source (deterministic | classifier | guard | fail_closed)`, topic, intent,
mode, explicitness, confidence (classifier only), reason_codes, classifier
invocation flag, shadow flag. Written to bounded counters/logs only in
content-free form.

### C4 — Workflow context record (internal, typed)

`workflow_family, resource_type, resource_id (opaque), status_class,
last_operation, allowed_next_operations, pending_confirmation | null,
created_at, expires_at`. Stored in-process, keyed by
(tenant, session, kb), TTL-bounded, size-bounded, invalidated on destructive
transitions observed in tool results, ignored when inconsistent with
authoritative server state. Eviction is deterministic and bounded: expired
entries are purged first; if the registry remains at capacity after purging,
creation of new state is rejected with a typed, sanitized, fail-closed
response (degrading to clarification/RAG per the deterministic policy —
never a guessed mutation); live confirmations and workflow contexts are
never silently evicted; only content-free capacity and rejection metrics are
exposed; state never spills into an unapproved persistent store. Never
contains evidence bodies, file contents, ACP payloads, provider responses,
secrets, or custom user metadata.

**Pending confirmation state (typed, server-controlled).** A bare-affirmative
follow-up ("Yes." / "Do it." / "Approve it." / "Activate that one." /
"Sì." / "Confermalo." / "Attiva quello.") may act only when a pending
confirmation exists that binds ALL of:

- tenant;
- trusted principal or session;
- workflow family;
- exact operation (closed vocabulary);
- exact resource type;
- exact opaque resource ID;
- exact version where applicable;
- previous authoritative state (typed status class);
- allowed next transition;
- creation timestamp;
- expiry;
- correlation ID.

The pending confirmation is tenant-scoped, session-scoped, bounded,
expiring, invalidated after use, invalidated after authoritative state
change, and validated against the current server state at consumption.
Cross-tenant, expired, mismatched, or stale confirmations fail closed.
Conversation history alone is insufficient. Classifier output alone is
insufficient. The classifier may resolve linguistic references ("that one",
"quello") to identify which pending confirmation the user likely means, but
it MUST NOT create or change the pending confirmation resource; creation and
mutation happen only in deterministic routing and typed tool-outcome paths.

### C5 — Streaming typed error and streaming policy

See §Streaming policy for the full normative behavior. Contract summary:

Streaming requests whose deterministic classification is a supported
workflow intent (mutation or safe proposal) receive an HTTP 409 JSON body
with code `workflow_stream_unsupported` and a typed, machine-readable
`detail` object containing: `code`, `message`, `workflow_family` (only when
safely known deterministically), `retry {mode, action, endpoint}`,
`correlation_id`, `reason` (safe reason code). It MUST NOT contain raw
message content or tool arguments. Informational streaming messages keep the
unchanged cited SSE RAG passthrough. Workflow-adjacent ambiguous streaming
messages receive a neutral streamed clarification (no classifier call, no
tools). No new SSE event types are introduced. Mode `off` preserves the
legacy streaming behavior exactly (including the D4 defect, documented).

### C6 — Internal classifier endpoint (Core): trust boundary

`POST /v1/intent/classification`, registered on Core's internal API
application. This is a service-to-service endpoint with a defined trust
boundary, not merely an "internal" path:

- **Sole ordinary application caller:** the Gateway. The endpoint is not a
  public user-facing classification service.
- **Service-to-service authentication:** requests MUST carry the deployment's
  internal service credential (shared secret from validated configuration,
  header-based) or an equivalent trusted network identity. Requests without
  it are rejected (401/403 typed error).
- **Network exposure and binding:** the endpoint is bound to Core's internal
  service network. The default deployment does not publish it to the host;
  publishing it is a security-relevant deployment decision that MUST be
  documented (constitution §41) and requires the typed OpenAPI contract
  below.
- **Gateway proxying:** the Gateway does NOT proxy this endpoint through any
  public route; no public Gateway path reaches it.
- **Browser access:** forbidden and technically enforced — service
  authentication, `application/json` content-type only (415 otherwise), no
  CORS, no HTML rendering. Obscurity, path naming, and lack of frontend links
  are NOT access control and are not relied upon.
- **Request-size limit:** request body capped (`INTENT_CLASSIFIER_MAX_REQUEST_BYTES`,
  default 32768; over-limit → typed 413-equivalent error); normalized
  message capped (`INTENT_CLASSIFIER_MAX_INPUT_CHARS`, default 2000,
  deterministic truncation).
- **Context-size limit:** workflow-context summary capped
  (`AGENT_INTENT_CLASSIFIER_MAX_CONTEXT_TURNS`, default 4; structured summary
  only).
- **Content-type:** `application/json` only.
- **Timeout:** 10 s default (bounded, configurable), applied client- and
  server-side.
- **Bounded retries:** at most 2 with backoff; classification is read-only
  and idempotent; no retry after client cancellation.
- **Concurrency bound:** bounded semaphore (`INTENT_CLASSIFIER_MAX_CONCURRENT_REQUESTS`,
  default 8); excess requests receive a typed busy error.
- **Rate limit:** per-caller token bucket (`INTENT_CLASSIFIER_RATE_LIMIT_PER_MINUTE`,
  default 120, deployment-global); excess → typed 429-equivalent error.
- **Cancellation:** cooperative — client disconnect aborts the upstream
  provider call; no result is persisted or replayed.
- **Logging and retention:** content-free only (safe error category,
  counters, latency, correlation ID). Prompts, messages, and full responses
  are never logged or retained.
- **Regional routing:** the endpoint adds no new region; the classifier
  transport behind it enforces the configured regional policy (EU or
  approved) with no fallback.
- **Error sanitization:** typed error codes only
  (`classifier_unavailable | classifier_invalid_output |
  regional_policy_rejected | classifier_disabled`); no raw provider errors,
  prompts, credentials, secret-bearing URLs, signed requests, or stack
  traces.
- **Startup and readiness:** the classifier is an optional capability
  (constitution §18) — its absence never blocks Core readiness; strict
  startup validation fails fast on invalid configuration when the classifier
  is enabled; a degraded `classifier` section appears in the internal status
  surface.
- **Public OpenAPI contract:** the endpoint is intentionally NOT part of the
  public OpenAPI contract (constitution §41: internal endpoints are not
  public APIs). Non-public status is technically enforced by service
  authentication plus internal-network binding (above), not by obscurity. If
  a supported deployment chooses to expose it externally, it MUST first gain
  a typed API contract and OpenAPI documentation through the normal
  governance process.

**Trust-boundary invariant (normative):**

> Calling the classification endpoint directly cannot bypass Gateway
> routing, trusted-principal resolution, tenant resolution, workflow-state
> validation, explicit-intent guards, tool authorization, or audit.

This holds structurally: the endpoint accepts a normalized message, a typed
workflow-context summary, and a prompt version; it has no tool registry
access, accepts no tenant/user/session identity, performs no business
mutation, and returns only an untyped-authority classification record that
the Gateway re-validates. Consequential operations remain reachable only
through the Gateway's agent loop, its typed tools, and the CRM extension's
authorization and audit.

### C7 — Configuration and confidence policy

Gateway (routing policy, prefix `AGENT_INTENT_ROUTER_*` where new):
`AGENT_INTENT_ROUTER_MODE` (`off|shadow|active`, default `off`),
`AGENT_INTENT_ROUTER_STRICT_VALIDATION` (default true: reject incompatible
combinations at startup),
`AGENT_INTENT_CLASSIFIER_MIN_CONFIDENCE` (default 0.85; allowed range
[0.50, 1.00]; informational-intent acceptance threshold),
`AGENT_INTENT_CLASSIFIER_SAFE_WORKFLOW_MIN_CONFIDENCE` (default 0.90; allowed
range [0.50, 1.00]; MUST be ≥ `MIN_CONFIDENCE` — validated),
`AGENT_INTENT_CLASSIFIER_MAX_INPUT_CHARS` (default 2000),
`AGENT_INTENT_CLASSIFIER_MAX_CONTEXT_TURNS` (default 4),
`AGENT_INTENT_ROUTER_CONFIRMATION_TTL_SECONDS` (default 300; allowed
[60, 900]),
`AGENT_INTENT_CLASSIFIER_FAIL_MODE` (`clarify`, only permitted value).

Core (transport, mirrors reranking precedent):
`INTENT_CLASSIFIER_ENABLED` (default false),
`INTENT_CLASSIFIER_PROVIDER` (`openrouter|bedrock`),
`INTENT_CLASSIFIER_MODEL`, `INTENT_CLASSIFIER_BASE_URL`,
`INTENT_CLASSIFIER_API_KEY` (secret reference),
`INTENT_CLASSIFIER_TIMEOUT_SECONDS` (default 10, bounded),
`INTENT_CLASSIFIER_MAX_RETRIES` (default 1, max 2),
`INTENT_CLASSIFIER_STRICT_STARTUP_VALIDATION` (default false),
`INTENT_CLASSIFIER_ENFORCE_EU_REGION` (default false),
`INTENT_CLASSIFIER_ALLOWED_REGIONS` (default `eu-central-1`),
`INTENT_CLASSIFIER_PROMPT_VERSION` (default `1`),
`INTENT_CLASSIFIER_MAX_INPUT_CHARS` (server-side bound),
`INTENT_CLASSIFIER_MAX_REQUEST_BYTES` (default 32768),
`INTENT_CLASSIFIER_MAX_CONCURRENT_REQUESTS` (default 8),
`INTENT_CLASSIFIER_RATE_LIMIT_PER_MINUTE` (default 120),
`INTENT_CLASSIFIER_SERVICE_AUTH_TOKEN` (secret reference; the internal
service credential required by C6).

Secrets never enter fingerprints, logs, metrics, health output, or results.
`VISUAL_MODEL` and `RERANK_MODEL` domains are not reused.

**Confidence threshold semantics (deterministic):** a classifier result is
accepted for its class iff `confidence >= threshold` (inclusive). The exact
boundary (`confidence == threshold`) is accepted and is covered by a
dedicated deterministic test. Informational intents use
`MIN_CONFIDENCE`; safe workflow proposal/analysis intents use
`SAFE_WORKFLOW_MIN_CONFIDENCE` (≥ informational). **Consequential operations
have no classifier threshold path at all** — no configuration value can
create one, and no threshold (however high) routes a consequential
operation; the deterministic explicit-intent guard is the only path
(§Active-mode classifier authority). Lower thresholds for consequential
actions are therefore not representable, not merely discouraged.

**Threshold invariance (normative):** thresholds MUST NOT vary by tenant,
user, selected Knowledge Base, custom metadata, message contents, or model
output. They are process-global settings read from validated configuration;
no request field, classifier field, or runtime input can alter them.
Per-tenant, per-user, per-KB, and model-selected thresholds are out of scope
and would require the full constitution §11 process.

**Malformed and conflicting confidence (normative):** missing confidence,
string-typed confidence, NaN, infinity, values outside [0,1], or otherwise
malformed values are invalid output → clarification. Conflicting fields —
topic inconsistent with intent, intent inconsistent with mode, reason codes
conflicting with the selected intent — are invalid output → clarification. A
high confidence value NEVER overrides: deterministic safety analysis,
negation, quotation, hypothetical framing, explicit-intent guards,
workflow-state validation, permission checks, tenant checks, or regional
policy.

## Gateway/Core responsibility split

**Gateway owns (control plane — application workflow policy):**

- deterministic intent analysis;
- routing policy;
- final route selection;
- explicit-intent guards;
- typed workflow context;
- pending confirmation state;
- clarification policy;
- agent-loop entry;
- grounded-RAG entry;
- streaming compatibility behavior;
- enforcement that classifier output remains untrusted.

**Core owns (data plane — model transport):**

- provider-neutral model transport;
- regional endpoint enforcement;
- strict classifier configuration validation;
- minimal classifier prompt construction;
- strict structured-output validation;
- bounded provider retries;
- sanitized classifier transport errors;
- content-free classifier health metadata.

Core MUST NOT select the final route. The classifier response returned by
Core is an untrusted semantic recommendation; the Gateway validates it and
applies deterministic policy.

**Ownership invariant (normative):**

> Model transport belongs in Core; application workflow policy belongs in
> Gateway.

This preserves the control-plane/data-plane boundary (constitution §1, §9;
ADR-0001 Option C rejection): all provider credentials, endpoints, regional
enforcement, and transport failure handling stay in the single component
that already talks to model providers, so EU enforcement and provider
validation are not duplicated or bypassed; all decisions about which
authorized workflow a chat turn enters — and every guard that keeps
consequential actions behind explicit intent — stay in the policy choke
point that terminates authentication and owns sessions. Nothing in the
classifier path gives Core a route decision, a tool, or a tenant.

## No-recursion invariant

The classifier request MUST NOT pass through the ordinary chat endpoint,
the intent router, the bounded agent loop, RAG answer generation, or tool
execution.

**Permitted flow (normative):**

```
Gateway chat router
  -> dedicated Core classification transport
  -> typed IntentClassification response
  -> Gateway deterministic decision policy
```

**Forbidden flow:**

```
classification request
  -> ordinary chat endpoint
  -> Gateway router
  -> classification request
```

Enforcement:

- a dedicated internal transport: the Gateway classification adapter calls
  `POST /v1/intent/classification` directly via the Core client; it never
  uses `/v1/chat/completions` and never enters the agent loop or RAG path;
- route separation plus a purpose marker: internal classification requests
  carry a dedicated purpose header (e.g. `X-Retriva-Internal-Purpose:
  intent-classification`) used for observability and for deterministic
  tests of the separation;
- no classifier call from within classifier handling: the classification
  path has a single call site (the routing pipeline's AMBIGUOUS branch) and
  no loop; a response is never re-classified;
- no tool availability: the Core classification endpoint has no tool
  registry access, so no tool can trigger the router recursively from within
  classification;
- bounded failure handling: recursion-shaped failures (timeouts, errors)
  degrade to clarification, never to a retry storm (bounded retries ≤ 2).

Deterministic tests cover direct recursion prevention (a classifier
response can never cause another classifier call for the same turn) and
indirect recursion prevention (no path from classification to the chat
endpoint, router, agent loop, or RAG generation).

## Streaming policy

Streaming remains free from Company Intelligence tool execution in this
milestone. Mode `off` preserves legacy streaming behavior exactly
(everything SSE RAG passthrough, including the documented D4 defect); the
behavior below applies when the router is enabled (`shadow` or `active`;
in `shadow` it is deterministic-only, no classifier influence).

### 7.1 Clear informational streaming request

Example: "How does ACP activation work?"

- remains on streaming grounded RAG (unchanged cited SSE passthrough);
- no business tool;
- no 409;
- no workflow mutation;
- normal cited streaming answer.

### 7.2 Clear deterministic workflow request over streaming

Example: "Activate ACP version acpver_123."

- no tool execution;
- the stream does not start; the client receives a typed HTTP 409 JSON body
  (the accepted streaming-compatible equivalent — the routing decision is
  made before any SSE bytes are emitted) with `code:
  "workflow_stream_unsupported"`;
- the body identifies that the request requires the supported non-streaming
  workflow and provides a machine-readable retry instruction:
  `workflow_family` (when safely known deterministically), `retry.mode`
  (`non_streaming`), `retry.action` (resend without `stream`), `retry.endpoint`
  (the non-streaming chat endpoint), `correlation_id`, `reason` (safe reason
  code);
- it MUST NOT contain raw message content or tool arguments;
- it never claims execution and never falls back to a text-only workflow
  simulation (the D4 fix).

### 7.3 Ambiguous streaming request — chosen policy: no classifier call

For ambiguous streaming requests the classifier is NOT called in this
milestone. Behavior:

- workflow-adjacent ambiguous streaming request → a concise neutral
  clarification, delivered as the streamed response content (SSE opens
  normally, emits the deterministic clarification text, closes); no
  classifier call, no tools, no RAG retrieval, no guessing;
- non-adjacent ambiguous streaming request (no workflow signal) → unchanged
  SSE grounded RAG.

Justification: (a) the streaming hot path gains no new provider latency,
cost, or failure mode; (b) the only decision classification could inform
here is RAG-vs-retry-non-streaming, and a neutral clarification is strictly
safer than either guess — a wrong RAG guess risks a text-only workflow
simulation (D4) and a wrong retry guess annoys informational users; (c) it
preserves the milestone invariant that streaming executes no business tools
and gains no new authority; (d) it is deterministic and testable.

If classifier-on-streaming is ever enabled in a future accepted change, it
remains bound to: ambiguity-only invocation; result may select only
streaming RAG or retry-non-streaming; it may NOT select the bounded agent
loop; it may NOT authorize an operation; insufficient confidence or any
consequential signal returns the neutral clarification or
`workflow_stream_unsupported`.

No streaming response ever claims a mutation occurred.

## Active-mode classifier authority (narrowed)

The first ACTIVE rollout permits classifier influence ONLY over:

- ambiguous informational routing;
- ambiguous non-destructive analysis;
- ambiguous proposal creation;
- clarification selection.

The classifier MUST NOT select, confirm, or authorize:

- approval;
- commit;
- campaign addressed confirmation;
- activation;
- supersession;
- rollback;
- deactivation;
- paid-provider approval;
- organization merge;
- exclusion activation;
- canonical destructive mutation;
- any other consequential state transition.

For consequential operations, classifier output MAY:

- identify the likely workflow family;
- identify that the message may concern a consequential action;
- request a focused clarification;
- identify the typed workflow context needed.

It MUST NOT route directly into the consequential tool. Deterministic
explicit-intent guards remain the only path into those operations. This
limitation is normative in spec.md (this section), architecture.md,
acceptance.md, plan.md, tasks.md, and ADR-0002 — not only in rollout
documentation.

## Multi-intent policy

**Chosen behavior: B — request clarification before entering any workflow.**
A MULTI-INTENT message never enters a workflow; it receives a deterministic
clarification from the closed template set, listing only the detected
workflow families (no raw content echo).

- never execute the consequential portion automatically;
- never interpret "then" (or "e poi", ";") as standing authorization for a
  later mutation;
- never chain analysis into approval, commit, activation, supersession,
  rollback, mark-addressed, or another consequence;
- one message cannot bypass separate intent boundaries;
- the classifier cannot create an execution plan containing multiple tool
  calls (contract C2 has no plan field; the agent loop and guards are
  unchanged);
- a message containing multiple consequential operations requires
  clarification and executes none of them.

The policy is deterministic: MULTI-INTENT is detected by the rule engine
(multiple family/operation matches, or conjunction/sequencing patterns) and
optionally flagged by a classifier reason code; both paths produce
`CLARIFICATION_REQUIRED`. Option A (respond to the informational portion,
then ask separately for explicit mutation authorization, with the pending
consequence tracked as typed state) is a possible future extension requiring
its own acceptance; it is not implemented in this milestone. English and
Italian evaluation cases are mandatory (acceptance.md TR59-TR66).

## Shadow-mode privacy

Shadow mode MUST NOT persist or emit: raw user messages; classifier prompts;
full classifier responses; conversation history; tool arguments; company
names; customer codes; tenant IDs; user IDs; session IDs; resource IDs;
business identifiers; arbitrary resource references; retrieved documents;
ACP payloads; import contents; campaign members; qualification evidence.

Permitted shadow-mode records are limited to safe structured values:

- classifier schema version;
- prompt version;
- provider/configuration fingerprint excluding secrets;
- deterministic route category;
- classifier route category;
- workflow family;
- interaction mode;
- explicitness class;
- agreement or disagreement flag;
- confidence bucket (bounded buckets, e.g. `[0.50,0.70) | [0.70,0.85) |
  [0.85,1.00]` — never raw unbounded confidence as a metric label);
- safe reason codes;
- latency;
- token and cost counters where safely aggregated;
- regional-policy result;
- safe error category;
- timestamp;
- deployment mode.

Shadow mode MUST NOT create a persistent message-level corpus. Default
behavior is aggregate metrics plus bounded ephemeral in-process diagnostics
(ring buffer, TTL- and size-bounded, lost on restart, never persisted).
Per-message persistence of any kind — even of safe fields — is out of scope
for this milestone. The workflow-context registry (C4) is routing state, not
shadow telemetry, and is never emitted.

If offline review of actual messages is ever needed, it requires a
separately approved privacy-safe sampling process using: synthetic messages;
explicitly authorized content; documented retention; access control;
minimization; deletion; audit. Confidential production messages MUST NOT be
used to build training or evaluation datasets (the evaluation dataset is
synthetic-only; acceptance.md TR58).

Retention, access, and deletion for permitted structured shadow records:
ephemeral diagnostics are bounded by TTL (default 15 minutes) and capacity
(default 1000 entries) and are lost on restart; aggregate counters reset on
restart; the internal status surface exposing them is auth-protected,
bounded, and sanitized; no deletion job is required because nothing
persists. Should a future accepted change persist structured shadow records,
it must document retention bounds, access control, and deletion before
implementation.

## Classifier failure behavior

Core classifier unavailability returns a typed, sanitized failure
(`classifier_unavailable | classifier_timeout | classifier_invalid_output |
regional_policy_rejected | classifier_disabled`). It MUST NOT silently
invoke:

- the ordinary chat model;
- the RAG answering model;
- the visual model;
- the reranker;
- another provider;
- a global endpoint;
- a lower-security endpoint.

The Gateway then applies deterministic policy:

- clear deterministic requests retain their deterministic route;
- ambiguous informational requests receive a clarification or the safe
  informational route according to accepted policy (workflow-adjacent →
  clarify; non-adjacent → RAG);
- ambiguous safe workflow requests receive clarification;
- ambiguous consequential requests receive clarification;
- no mutation is guessed;
- no disallowed provider fallback occurs.

Safe error categories are the closed taxonomy of architecture.md §Error
taxonomy. Raw provider errors, prompts, message content, credentials,
secret-bearing base URLs, signed requests, and stack traces are never
exposed to clients or logs (constitution §33).

## Governing invariant

The following invariant is normative for this pack and for ADR-0002:

> The intent classifier improves interpretation of ambiguous natural
> language. It does not grant authority, select tenants, choose providers,
> construct tool arguments, authorize state transitions, or execute tools.
>
> Gateway remains the sole owner of the final route decision.
>
> Deterministic rules remain authoritative for clear requests and every
> consequential action.
>
> If classification is unavailable, invalid, regionally disallowed,
> internally inconsistent, or below the accepted confidence threshold,
> Retriva preserves deterministic behavior and asks for clarification where
> necessary.
>
> Retriva never falls back to a disallowed provider, never guesses a
> consequential intent, and never converts a typed workflow failure into a
> generic RAG answer.

And, stated separately for emphasis:

> Classifier output is untrusted input to the Gateway decision policy.

## Safety invariants (normative)

S1 Routing is not authorization: every tool call keeps trusted principal,
tenant context, server-side permission, resource ownership, lifecycle state,
explicit intent, idempotency, audit, and transactional semantics; the
classifier never receives, returns, or overrides permissions.
S2 An LLM classification alone never authorizes a consequential mutation;
consequential operations require deterministic explicit intent plus accepted
workflow state plus permission checks.
S3 False positives are more dangerous than false negatives: uncertain
messages never enter a mutation-capable workflow because of topic words.
S4 Typed workflow errors never convert to generic RAG answers and never
re-invoke the classifier to escape a typed business error.
S5 No regional-policy fallback: the classifier uses only allowed regional
endpoints; unavailability never reroutes to a disallowed provider/region,
never disables authorization checks, and degrades to deterministic behavior
(clarification for ambiguous consequential, RAG only for clearly
informational); no other model (chat, RAG, visual, reranker) is implicitly
invoked on failure.
S6 Custom metadata never drives routing.
S7 Conversation history alone never authorizes a consequential action; bare
affirmatives act only against a typed, unexpired pending confirmation
binding exactly operation, tenant, principal/session, resource, version,
previous state, allowed transition, and expiry (C4).
S8 The classifier prompt treats the user message as untrusted data to
classify, never as instructions; no tool credentials or implementation
details are included; adversarial inputs are tested.
S9 Classifier calls carry minimum content: current normalized message
(truncated by deterministic rules), bounded typed workflow-context summary,
prompt version — never retrieved documents, company records, ACP payloads,
import attachments, campaign membership, qualification evidence, or tool
results containing company data. Tenant, user, and session identifiers are
not sent (data minimization, constitution §29).
S10 Metrics, logs, status output, and errors are content-free; no message
text, tenant/user/session IDs, resource IDs, or raw provider errors.
S11 The §Constitution §11 compatibility statement, the §Governing invariant,
the C6 trust-boundary invariant, the §Gateway/Core ownership invariant, and
the §No-recursion invariant are binding on every phase, test, and document
of this pack.

## Documentation (delivered in the same accepted change)

ADR-0002; this pack; Gateway routing + chat architecture documentation;
`.env.example` and deployment compose plumbing; security and
regional-routing notes; internal status endpoint documentation; metrics
documentation; operator rollout (shadow → active) and deterministic
rollback (mode `off`) procedures; dataset documentation; limitations
(streaming scope, single-process context registry, classifier coverage).

## Acceptance summary

Full criteria live in `acceptance.md`: deterministic suite (68 mapped
A-cases plus the TR matrix TR1-TR87 — TR1-TR60 preserving the source review
numbering, TR61-TR80 completing its unnumbered section requirements,
TR81-TR87 covering registry eviction and mode gating per the revision-2
repair), EN/IT evaluation gates with safety-first thresholds, shadow-mode
acceptance (routes unchanged by classifier recommendations, privacy-safe
records only), mode-gating and rollback proofs (`off` = exact legacy
behavior including the D5 503 body; TR84-TR87), limited active-hybrid
acceptance (ambiguous informational + safe proposal routes only), deployed
acceptance on an isolated tenant (cust_0007 untouched), and proof
obligations for S1-S11 and the revision-2 invariants.
