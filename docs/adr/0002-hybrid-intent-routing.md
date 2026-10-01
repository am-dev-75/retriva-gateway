# ADR-0002: Hybrid Intent Routing with an Ambiguity-Only LLM Classifier

- **Status:** ACCEPTED (revision 2) — Owner Acceptance Gate A approved
  2026-10-01 (including the Constitution §11 interpretation, the activation
  model, and the narrowed ACTIVE-mode authority); implementation proceeds
  only through the accepted spec-pack plan.md phase gates.
- **Date:** 2026-10-01 (revision 2: 2026-10-01)
- **Deciders:** Retriva owner (user), Kilo (code agent)
- **Scope:** retriva-gateway, retriva-core (internal classifier transport)
- **Spec pack:** `specs/001-hybrid-intent-routing/` (revision 2)
- **Extends (does not amend):** ADR-0001 (extension tools for the chat agent
  loop); CRM ADR-023 (chat-tool integration, stage separation, activation
  never inferred); CRM ADR-024 (evidence enrichment tools); CRM ADR-022
  principle 6 (provider/regional policy); the Retriva constitution v1.1
  (`retriva-core/.agent/rules/retriva-constitution.md`), which remains the
  highest authority.
- **Governance follow-up recorded (not resolved here):** GF-001 —
  constitution §11's reranker "governing ADR" reference dangles;
  `retriva-core/docs/governance/GF-001-dangling-reranker-adr-reference.md`.

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

The owner reviewed the original proposal and required revisions ("accept
with changes"); revision 2 of this ADR and the spec pack applies them. The
architectural principle is unchanged: **LLM for ambiguous language
understanding; deterministic code for authority, workflow state, and
consequences.**

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

## Constitution §11 compatibility (workflow dispatch vs provider/model routing)

This ADR keeps two decision domains separate:

**A. Workflow dispatch (application-level):** grounded RAG; the bounded
Company Intelligence agent loop; clarification.

**B. Provider and model routing (transport-level):** provider, model,
endpoint, region and residency selection; security posture; retention
policy.

The hybrid classifier may inspect the current authorized chat request to
recommend workflow dispatch (A) only. It must not use message content,
conversation content, selected Knowledge Base, custom metadata, classifier
output, or user instructions to choose provider, model, base URL, endpoint,
region, residency policy, data-retention policy, security mode, or
confidence threshold (B).

> This feature classifies the requested interaction and recommends one of
> the already authorized application workflows. It does not perform
> content-dependent provider or model routing.
>
> The classifier provider, model, endpoint, region, and security policy are
> selected only through validated deployment configuration. User messages,
> conversation content, Knowledge Base selection, custom metadata, and
> classifier output cannot alter those choices.

**Why this is compatible with §11:** §11's normative objects are providers
and models — selection MUST go through validated configuration and
provider-neutral interfaces and MUST NOT be inferred from arbitrary user
content, custom metadata, model-generated suggestions, or untrusted request
fields. This design performs no such inference: the classifier's provider,
model, endpoint, region, and security policy are fixed, deployment-global,
validated configuration (the accepted reranker pattern), and no message,
metadata, KB selection, or classifier output can alter them. Application-
workflow dispatch, by contrast, is control-plane orchestration (constitution
§9: the Gateway is the policy and orchestration choke point; every
consequential action is represented by an explicit workflow or contract)
and is necessarily content-dependent — the accepted, deployed, tested
production router already dispatches on message content, and a system that
could not interpret which authorized workflow a request concerns could not
route it to that workflow's explicit contract (§6/§9/§30). The classifier's
output is a model-generated suggestion, which §11 explicitly bars from model
routing — so classifier output is hard-forbidden from every domain-B choice
and only recommends workflow dispatch, re-validated by deterministic Gateway
policy. No tenant-, KB-, user-, or request-specific classifier selection is
introduced; model failure never silently routes confidential data to a
disallowed provider, region, or endpoint.

**Conclusion (explicit, not silent):** §11 forbids content-dependent
provider/model/endpoint/region selection; it does not forbid
content-dependent application-workflow dispatch. No constitution amendment
is required for this ADR. This interpretation is recorded for owner
acceptance; if the owner rejects it, the constitutionally required fallback
(§5) is an amendment proposal, not a quiet reinterpretation in code.

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

Option A, as specified in `specs/001-hybrid-intent-routing/` (revision 2):

- Closed, versioned taxonomy separating topic, intent, interaction mode,
  explicitness, confidence, clarification, and opaque resource reference.
- Deterministic rules with priorities and reason codes; documentation
  framing, negation, hypothetical, and quoted/code content are vetoed from
  command routing; EN/IT normalization; narrowed enrichment matching (D3);
  deterministic MULTI-INTENT detection → clarification, never partial
  execution.
- Typed, session/tenant-scoped, bounded, expiring workflow-context registry,
  armed by deterministic routing and typed tool outcomes only; production
  cross-turn follow-ups become possible (D1) while bare affirmatives act
  only on typed, unexpired pending confirmations binding tenant, principal
  or session, workflow family, exact operation, resource type, opaque
  resource ID, version, previous authoritative state, allowed next
  transition, creation timestamp, expiry, and correlation ID —
  single-use, invalidated on authoritative state change, re-validated
  against current server state, failing closed when cross-tenant, expired,
  mismatched, or stale. Conversation history alone and classifier output
  alone are insufficient; the classifier may resolve linguistic references
  but never creates or changes the confirmation resource.
- Explicit-intent guards independent of the classifier for all consequential
  operations.
- Strict structured classifier contract (closed schema, additionalProperties
  false, no authority, route, or execution-plan fields) re-validated by the
  Gateway; invalid output — including missing, malformed, non-finite, or
  string-typed confidence and field conflicts — → clarification, never
  permissive routing.
- Core-owned classifier transport: provider-neutral (`openrouter|bedrock`
  initially), EU-region enforcement without fallback, bounded
  timeout/retries, secrets as references, strict startup validation,
  sanitized failures; on failure no other model (chat, RAG, visual,
  reranker) and no alternate provider, global, or lower-security endpoint is
  implicitly invoked.
- Content-free observability; no message content, identifiers, or raw
  provider errors in metrics/logs/status; shadow records restricted to the
  privacy allowlist (confidence buckets, never raw; no identifiers, no
  content; no persistent message-level corpus).
- Rollout: off (legacy) → shadow (new pipeline with safe structured records
  only) → active (narrowed authority). Rollback = set mode `off`, which
  restores the legacy router and legacy externally observable behavior
  (§Activation model).

### Gateway/Core responsibility split

Gateway owns: deterministic intent analysis; routing policy; final route
selection; explicit-intent guards; typed workflow context; pending
confirmation state; clarification policy; agent-loop entry; grounded-RAG
entry; streaming compatibility behavior; enforcement that classifier output
remains untrusted. Core owns: provider-neutral model transport; regional
endpoint enforcement; strict classifier configuration validation; minimal
classifier prompt construction; strict structured-output validation;
bounded provider retries; sanitized classifier transport errors;
content-free classifier health metadata. Core never selects the final route.

> Model transport belongs in Core; application workflow policy belongs in
> Gateway.

This preserves the control-plane/data-plane boundary (constitution §1, §9;
ADR-0001 Option C rejection): one component operates all model transports
(no second egress path, no duplicated EU enforcement), and the policy choke
point that terminates authentication owns every workflow decision and guard.

### Classification endpoint trust boundary

`POST /v1/intent/classification` is a service-to-service endpoint, not
merely "internal": the Gateway is the only ordinary application caller; it
is not a public user-facing classification service; service-to-service
authentication (internal service credential or trusted network identity) is
required; it binds to the internal service network and is not published by
the default deployment; the Gateway does not proxy it publicly; direct
browser access is forbidden and technically enforced (authentication, JSON
content-type only, no CORS); request-size, context-size, timeout, bounded
retry, concurrency, and rate limits are enforced; cancellation is
cooperative; logging is content-free; regional policy applies to the
transport behind it; errors are sanitized typed codes; readiness never
depends on the classifier (constitution §18); it is intentionally excluded
from the public OpenAPI contract, with non-public status enforced by
authentication and binding — not by obscurity, path naming, or missing
frontend links — and external exposure in a supported deployment requires a
typed API contract and OpenAPI documentation first.

> Calling the classification endpoint directly cannot bypass Gateway
> routing, trusted-principal resolution, tenant resolution, workflow-state
> validation, explicit-intent guards, tool authorization, or audit.

### No-recursion invariant

The permitted flow is: Gateway chat router → dedicated Core classification
transport → typed IntentClassification response → Gateway deterministic
decision policy. The forbidden flow is: classification request → ordinary
chat endpoint → Gateway router → classification request. Enforcement:
dedicated transport (never `/v1/chat/completions`, never the agent loop or
RAG), route separation plus a purpose marker, a single call site with no
re-classification loop, no tool availability in the classification path, and
bounded failure handling. Direct and indirect recursion prevention are
deterministically tested.

### Streaming policy

Streaming executes no business tools in this milestone. Clear informational
streaming requests ("How does ACP activation work?") keep the unchanged
cited grounded-RAG SSE. Clear deterministic workflow requests over
streaming ("Activate ACP version acpver_123.") execute no tool and return a
typed HTTP 409 `workflow_stream_unsupported` whose machine-readable body
identifies the workflow family when safely known, the supported
non-streaming endpoint and client action, the retry mode, a correlation ID,
and a safe reason code — never raw message content or tool arguments, never
a claim of execution, never a text-only workflow simulation (D4). For
ambiguous streaming requests the classifier is NOT called (chosen policy):
workflow-adjacent ambiguity returns a concise neutral streamed
clarification; non-adjacent ambiguity keeps RAG. Justification: the
streaming hot path gains no provider latency, cost, or failure mode; a
neutral clarification is strictly safer than guessing RAG versus
retry-non-streaming; the milestone keeps streaming free of new authority;
the behavior is deterministic and testable. A future option, if ever
accepted, remains ambiguity-only and limited to choosing streaming RAG or
retry-non-streaming — never the agent loop, never authorization. Mode `off`
preserves legacy streaming exactly.

### Narrowed ACTIVE-mode classifier authority

The first ACTIVE rollout permits classifier influence only over: ambiguous
informational routing; ambiguous non-destructive analysis; ambiguous
proposal creation; clarification selection. The classifier must not select,
confirm, or authorize approval, commit, campaign addressed confirmation,
activation, supersession, rollback, deactivation, paid-provider approval,
organization merge, exclusion activation, canonical destructive mutation, or
any other consequential state transition. For consequential operations,
classifier output may identify the likely workflow family, flag that the
message may concern a consequential action, request a focused clarification,
or identify the typed workflow context needed — it must not route directly
into the consequential tool. Deterministic explicit-intent guards remain the
only path. This limitation is stated in spec.md, architecture.md,
acceptance.md, plan.md, tasks.md, and this ADR.

### Confidence policy

Thresholds are validated deployment configuration: informational acceptance
threshold default 0.85 (allowed [0.50, 1.00]); separate safe-workflow
threshold default 0.90, always ≥ the informational threshold; semantics are
`confidence >= threshold` (inclusive), with the exact boundary
deterministically tested; consequential operations have no classifier
threshold path at all — no configuration can create one, so lower
thresholds for consequential actions are not representable. Missing,
string-typed, NaN, infinite, out-of-range, or malformed confidence and
conflicting fields (topic/intent, intent/mode, reason-code/intent) are
invalid output → clarification. A high confidence value never overrides
deterministic safety analysis, negation, quotation, hypothetical framing,
explicit-intent guards, workflow-state validation, permission checks,
tenant checks, or regional policy. Thresholds never vary by tenant, user,
Knowledge Base, custom metadata, message contents, or model output.

### Multi-intent policy

Chosen behavior: request clarification before entering any workflow
(option B). Multi-intent messages ("Explain the current ACP and activate the
newest approved version.", "Analyze this import and commit it if there are
no errors.") never execute their consequential portion; "then" is never
standing authorization; analysis is never chained into approval, commit,
activation, supersession, rollback, mark-addressed, or another consequence;
one message cannot bypass separate intent boundaries; the classifier cannot
create an execution plan containing multiple tool calls; multiple
consequential operations in one message clarify and execute none. Detection
is deterministic with classifier reason-code support; English and Italian
evaluation cases are required. Safe decomposition (option A) is a possible
future extension requiring its own acceptance.

### Activation model, rollback, and D5 resolution

`AGENT_INTENT_ROUTER_MODE` gates which router executes (normative; identical
to spec §Activation model):

1. **`off`** (default, rollback state) invokes the legacy routing path and
   preserves legacy externally observable behavior, including the documented
   D1-D5 defects where they exist; the new deterministic fixes, guards,
   clarification and multi-intent policies, confidence behavior,
   pending-confirmation state, and classifier are not active (the classifier
   is never called); AMBIGUOUS / workflow-adjacency labels may be computed
   for shadow observation only where applicable and never alter the route.
2. **`shadow`** activates the new deterministic pipeline and its D1-D5
   fixes, applies the new guards and policies, may invoke the classifier
   only for eligible deterministic AMBIGUOUS outcomes, records the
   recommendation with the accepted privacy-safe telemetry, and never lets
   the recommendation change the deterministic route (route-neutral with
   respect to classifier recommendations, not necessarily identical to
   legacy routing).
3. **`active`** retains everything from `shadow` and permits classifier
   influence only within the narrowly accepted non-consequential ambiguity
   scope, preserving every prohibition and governing invariant.

**D5 resolution:** the revised generic (family-neutral) agent-unavailable
HTTP 503 response is part of the new pipeline, externally effective only in
`shadow` and `active`. No already accepted requirement mandates the generic
text in `off`, so `off` preserves the exact legacy qualification-specific
503 body, keeping `off` a genuine behavioral rollback. Streaming is
mode-specific: legacy SSE passthrough in `off`; the C5 typed 409 and neutral
clarification behaviors in `shadow`/`active`.

## Governing invariant

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

And: **Classifier output is untrusted input to the Gateway decision
policy.**

## Governance follow-up (recorded, not resolved here)

Constitution §11 defines the accepted reranker policy "as defined by the
governing ADR", but no reranker ADR exists. This is recorded as **GF-001**
at `retriva-core/docs/governance/GF-001-dangling-reranker-adr-reference.md`
with two permitted resolutions (create the missing reranker ADR from the
accepted implementation, or amend the dangling reference through the proper
governance process). This ADR does not fix the reference, does not govern
reranking, changes no reranker behavior, and proposes no constitution
amendment.

## Consequences

- **Positive:** ambiguous natural-language and multilingual workflow recall
  improves without touching the authorization boundary; deterministic
  behavior is preserved and testable; classifier egress is minimal, regional
  and revocable; the D1-D5 fixes are implemented by the new pipeline and
  become externally effective in `shadow` and `active` (§Activation model);
  the §11 boundary, endpoint trust boundary,
  ownership split, recursion, streaming, confidence, shadow-privacy,
  multi-intent, and confirmation-state requirements of the owner review are
  specified and testable (TR1-TR87).
- **Costs:** one additional model call for genuinely ambiguous messages
  only (measured and reported); a new internal Core endpoint and config
  domain to operate; workflow context is single-process (documented
  limitation).
- **Security:** no new authorization surface; the classification endpoint
  cannot bypass routing, guards, or audit; classifier output carries no
  authority; regional violations are typed errors, never silent reroutes;
  shadow telemetry is content-free by allowlist.
- **Compatibility:** no public chat contract change except the narrow
  streaming typed error (C5); mode `off` reproduces legacy routing exactly,
  including the documented D1-D5 defects where they exist (among them the
  exact legacy qualification-specific agent-unavailable 503 body, per the
  D5 resolution); tool registry, permissions, and tenant semantics
  unchanged.
