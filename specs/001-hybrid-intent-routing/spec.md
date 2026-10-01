# Feature Spec — Hybrid Intent Routing for Retriva Chat (v1)

Spec pack: `001-hybrid-intent-routing`
Status: PROPOSED (awaiting owner review gate; no code changes before acceptance)
Governing ADR: ADR-0002 (`docs/adr/0002-hybrid-intent-routing.md`)
Extends: Gateway ADR-0001 (extension tools for the chat agent loop); CRM
Spec 020 / ADR-023 (accepted chat-tool surface and stage-separation policy);
CRM Spec 021 / ADR-024 (evidence enrichment tools). Supersedes, for chat
workflow routing only, the unaccepted `docs/sdd/SDD-Retriva-Gateway-Granular-
Intent-Detection.md` (its catalog-intent design was never accepted and its
non-workflow intents are production-dead). Changes no accepted public chat
API contract except the narrow streaming behavior listed in §Scope.

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

This spec fixes D1-D5 within the scope below.

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
   deterministic routing may write.
5. A provider-neutral classifier interface (`IntentClassifier`,
   `IntentClassification`, `IntentClassificationError`,
   `IntentClassifierConfig`) with strict structured-output validation; the
   Gateway treats results as untrusted recommendations and re-validates every
   field.
6. A dedicated Core classifier transport domain (`INTENT_CLASSIFIER_*`)
   behind an internal Core endpoint, mirroring the accepted reranking
   pattern: provider-neutral, strict startup validation, EU-region
   enforcement with no fallback, secrets as references, bounded
   timeout/retries/budgets.
7. Shadow mode (`off|shadow|active` mode switch, default `off`): shadow
   records classifier output as safe structured metadata without changing any
   route; activation to `active` is configuration-controlled and reversible
   (rollback switch = set mode `off`).
8. Focused clarification behavior (concise, action-specific, never
   tool-executing), including the streaming typed-error path.
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
- No retrofit of the production-dead catalog/metadata intents of the
  unaccepted SDD; they remain out of the chat routing pipeline.
- No deletion of `IntentDetector.analyze()` in this pack (deprecation is
  deferred; behavior-preserving).

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
mutation-authorization field. Fields: `schema_version, topic, intent, mode,
explicitness, confidence, requires_clarification, clarification_reason,
resource_reference (opaque string or null), language, reason_codes (bounded
closed list)`. Every field is re-validated deterministically by the Gateway;
any violation yields a safe classification failure (clarification), never
permissive routing.

### C3 — Route decision record (internal)

`route (AGENT_LOOP | RAG | CLARIFY | REFUSE_STREAM | LEGACY_RAG)`,
`source (deterministic | classifier | guard | fail_closed)`, topic, intent,
mode, explicitness, confidence (classifier only), reason_codes, classifier
invocation flag, shadow flag. Written to bounded counters/logs only in
content-free form.

### C4 — Workflow context record (internal, typed)

`workflow_family, resource_type, resource_id (opaque), status_class,
last_operation, allowed_next_operations, pending_confirmation {operation,
resource_id, requester_principal, tenant, kb, expires_at} | null,
created_at, expires_at`. Stored in-process, keyed by
(tenant, session, kb), TTL-bounded, size-bounded, invalidated on destructive
transitions observed in tool results, ignored when inconsistent with
authoritative server state. Never contains evidence bodies, file contents,
ACP payloads, provider responses, secrets, or custom user metadata.

### C5 — Streaming typed error

Streaming requests whose deterministic classification is a supported
workflow intent (mutation or safe proposal) receive an HTTP 409 JSON body
`{"detail": {"code": "workflow_stream_unsupported", "message": ...,
"retry": "non-streaming chat"}}` instead of a text-only RAG answer.
Informational and ambiguous streaming messages keep the unchanged SSE RAG
passthrough. No new SSE event types are introduced.

### C6 — Internal classifier endpoint (Core, not public)

`POST /v1/intent/classification` on the Core OpenAI-compatible API:
bounded input (normalized message, workflow-context summary, classifier
prompt version), returns the schema-C2 object or a typed error
(`classifier_unavailable | classifier_invalid_output | regional_policy_rejected |
classifier_disabled`). Internal contract documented in architecture.md; not
exposed through Gateway public routes.

### C7 — Configuration

Gateway (routing policy, prefix `AGENT_INTENT_ROUTER_*` where new):
`AGENT_INTENT_ROUTER_MODE` (`off|shadow|active`, default `off`),
`AGENT_INTENT_CLASSIFIER_MIN_CONFIDENCE` (default 0.85),
`AGENT_INTENT_CLASSIFIER_MAX_INPUT_CHARS` (default 2000),
`AGENT_INTENT_CLASSIFIER_MAX_CONTEXT_TURNS` (default 4),
`AGENT_INTENT_CLASSIFIER_FAIL_MODE` (`clarify`, only permitted value),
strict-validation flag rejecting incompatible combinations at startup.

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
`INTENT_CLASSIFIER_MAX_INPUT_CHARS` (server-side bound).
Secrets never enter fingerprints, logs, metrics, health output, or results.
`VISUAL_MODEL` and `RERANK_MODEL` domains are not reused.

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
informational).
S6 Custom metadata never drives routing.
S7 Conversation history alone never authorizes a consequential action;
bare affirmatives act only against a typed, unexpired pending confirmation
that identifies exact operation, tenant, resource, version, requester, and
expiry.
S8 The classifier prompt treats the user message as untrusted data to
classify, never as instructions; no tool credentials or implementation
details are included; adversarial inputs are tested.
S9 Classifier calls carry minimum content: current normalized message
(truncated by deterministic rules), bounded typed workflow-context summary,
prompt version — never retrieved documents, company records, ACP payloads,
import attachments, campaign membership, qualification evidence, or tool
results containing company data.
S10 Metrics, logs, status output, and errors are content-free; no message
text, tenant/user/session IDs, resource IDs, or raw provider errors.

## Documentation (delivered in the same accepted change)

ADR-0002; this pack; Gateway routing + chat architecture documentation;
`.env.example` and deployment compose plumbing; security and
regional-routing notes; internal status endpoint documentation; metrics
documentation; operator rollout (shadow → active) and deterministic
rollback (mode `off`) procedures; dataset documentation; limitations
(streaming scope, single-process context registry, classifier coverage).

## Acceptance summary

Full criteria live in `acceptance.md`: deterministic suite (68 mapped
cases), EN/IT evaluation gates with safety-first thresholds, shadow-mode
acceptance (zero route changes), limited active-hybrid acceptance
(ambiguous informational + safe proposal routes only), deployed acceptance
on an isolated tenant (cust_0007 untouched), and proof obligations for
S1-S10.
