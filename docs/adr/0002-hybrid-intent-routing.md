# ADR-0002: Hybrid Intent Routing with an Ambiguity-Only LLM Classifier

- **Status:** PROPOSED (awaiting owner review gate; no code before acceptance)
- **Date:** 2026-10-01
- **Deciders:** Retriva owner (user), Kilo (code agent)
- **Scope:** retriva-gateway, retriva-core (internal classifier transport)
- **Spec pack:** `specs/001-hybrid-intent-routing/`
- **Extends (does not amend):** ADR-0001 (extension tools for the chat agent
  loop); CRM ADR-023 (chat-tool integration, stage separation, activation
  never inferred); CRM ADR-024 (evidence enrichment tools); CRM ADR-022
  principle 6 (provider/regional policy).

## Context

Chat routing today is a single deterministic regex decision in the Gateway:
accepted Company Intelligence workflow intents enter the bounded agent loop;
everything else stays on grounded, cited RAG; streaming never enters the
agent loop. The boundary is safe but linguistically brittle: no negation,
hypothetical, quotation, or documentation-framing handling; cross-turn
continuation state is unreachable in production; Italian phrasing is matched
only literally. Verified defects D1-D5 are recorded in the spec pack.

An LLM classifier could fix the language understanding, but an LLM must
never become an authorization mechanism, must not fire on every message, and
must not create a new confidential-data egress path outside accepted
regional policy.

## Decision drivers

1. Deterministic routing remains first; the classifier is invoked **only**
   when deterministic routing returns AMBIGUOUS.
2. Routing is not authorization. Tool calls keep trusted principal, tenant,
   server-side permission, ownership, lifecycle state, explicit intent,
   idempotency, audit (ADR-023 decisions 2-4; constitution §30).
3. Consequential operations (approve/commit/activate/supersede/rollback/
   deactivate/mark-addressed/canonical import mutation/merge/exclusion
   activation/paid-provider approval) require deterministic explicit intent
   plus accepted workflow state plus permissions — independently of any
   classifier output.
4. EU/regional policy is technically enforced with no fallback (constitution
   §31; reranking precedent in `retriva-core/docs/reranking.md`).
5. Provider neutrality and a distinct configuration domain (constitution
   §11; VISUAL_MODEL/RERANK_MODEL not reused).
6. Optional capability ships disabled by default; disabled behavior is
   unchanged (constitution §18).
7. Typed workflow errors never fall back to RAG (accepted behavior,
   `test_chat_qualification_policy.py`).

## Considered options

### Option A — Deterministic-first pipeline with ambiguity-only classifier (chosen)

Typed deterministic rule engine → explicit-intent guards → LLM classifier
for AMBIGUOUS only → deterministic validation and decision policy →
clarification or safe fallback. Classifier transport lives in Core behind an
internal endpoint with a dedicated `INTENT_CLASSIFIER_*` domain, strict
startup validation, and EU enforcement (reusing the accepted reranking
pattern); the Gateway owns routing policy and treats classifier output as an
untrusted, re-validated recommendation. Shadow mode precedes active mode;
`AGENT_INTENT_ROUTER_MODE=off|shadow|active` (default `off`) is the rollout
and rollback switch.

### Option B — LLM-first routing with deterministic guardrails

Rejected: violates deterministic-first semantics (constitution §8) for every
message, adds cost/latency to all chats, and makes authorization-adjacent
behavior depend on model availability.

### Option C — Classifier inside the Gateway with direct provider calls

Rejected: introduces a second LLM transport outside Core, contradicts the
control/data-plane split (constitution §1, §9) and the ADR-0001 boundary
decision; EU enforcement and provider validation would be duplicated.

### Option D — Streaming agent protocol in this milestone

Rejected: adding tool/workflow events to the SSE passthrough is a public
API change requiring its own OpenAPI and compatibility design (constitution
§12). Spec 001 selects scoped option A of §15: streaming stays RAG;
detected workflow intents over streaming return a typed 409
`workflow_stream_unsupported` directing clients to the non-streaming path.

## Decision

Option A, as specified in `specs/001-hybrid-intent-routing/`:

- Closed, versioned taxonomy separating topic, intent, interaction mode,
  explicitness, confidence, clarification, and opaque resource reference.
- Deterministic rules with priorities and reason codes; documentation
  framing, negation, hypothetical, and quoted/code content are vetoed from
  command routing; EN/IT normalization; narrowed enrichment matching (D3).
- Typed, session/tenant-scoped, bounded, expiring workflow-context registry,
  armed by deterministic routing and typed tool outcomes only; production
  cross-turn follow-ups become possible (D1) while bare affirmatives act
  only on typed, unexpired pending confirmations.
- Explicit-intent guards independent of the classifier for all consequential
  operations.
- Strict structured classifier contract (closed schema, additionalProperties
  false, no authority fields) re-validated by the Gateway; invalid output →
  clarification, never permissive routing.
- Core-owned classifier transport: provider-neutral (`openrouter|bedrock`
  initially), EU-region enforcement without fallback, bounded
  timeout/retries, secrets as references, strict startup validation,
  sanitized failures.
- Content-free observability; no message content, identifiers, or raw
  provider errors in metrics/logs/status.
- Rollout: off (legacy) → shadow (record only) → active (ambiguous
  informational + safe proposals only; consequential operations remain
  guard-gated). Rollback = set mode `off`.

## Consequences

- **Positive:** ambiguous natural-language and multilingual workflow recall
  improves without touching the authorization boundary; deterministic
  behavior is preserved and testable; classifier egress is minimal, regional
  and revocable; D1-D5 are fixed.
- **Costs:** one additional model call for genuinely ambiguous messages
  only (measured and reported); a new internal Core endpoint and config
  domain to operate; workflow context is single-process (documented
  limitation).
- **Security:** no new authorization surface; classifier output carries no
  authority; regional violations are typed errors, never silent reroutes.
- **Compatibility:** no public chat contract change except the narrow
  streaming typed error (C5); mode `off` reproduces legacy routing exactly;
  tool registry, permissions, and tenant semantics unchanged.
