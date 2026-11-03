# Spec 040 — Catalog-Driven Semantic Intent Router for Retriva Chat Routing

- **Status:** ACCEPTED (Gate A passed 2026-11-03; revision 1)
- **Revision:** 1
- **Date:** 2026-11-03
- **Allocated:** 2026-11-03 in the project-wide sequence per Constitution
  §43 (renumbered at Gate A — see §12)
- **Repository:** `retriva-gateway`
- **Companion ADR:** ADR-045
  (`retriva-gateway/docs/adr/adr-045-catalog-driven-semantic-routing.md`)
- **Governing authority:** `retriva-core/.agent/rules/retriva-constitution.md`,
  v1.2, especially §18 (optional capabilities safe by default), §38 (phase
  gating), §42 (spec before code), and §43 (ADRs and registry allocation).
- **Extends, does not amend:** Spec 001 / ADR-0002 (hybrid intent routing
  and the ambiguity-only advisory classifier). The deterministic safety
  layer defined by Spec 001 remains unchanged and terminal.
- **Implementation:** Phase B AUTHORIZED at Gate A (2026-11-03).
  Phases C–E remain separately gated.

## 1. Purpose

Retriva has two souls:

- a **RAG soul** — grounded question answering over the knowledge base with
  citations, and
- a **deterministic soul** — relational Company Intelligence data reached
  only through the gateway agent loop's typed tools.

Production routing between them is a closed-world, hand-maintained
decision. This specification defines a **catalog-driven semantic router**
that reads the tool catalog — the actual, typed tools that exist — and
decides between grounded RAG and a read-only Company Intelligence family.
The authoritative decision boundary stays deterministic: the semantic
router may only choose a *data plane*, never an operation, tool, mutation,
or identity.

The program was owner-ratified on 2026-11-03 and Gate A passed the same
day. This pack records the decision and authorizes Phase B only; Phases
C–E remain gated.

## 2. Problem and production evidence

### 2.1 Observed miss

On 2026-11-02 a user asked the production chat:

> How many outreach campaigns have we done?

Retriva answered from RAG:

> I do not have sufficient evidence in my knowledge base to answer this
> question. None of the available sources contain any data regarding
> outreach campaigns.

with three irrelevant knowledge-base citations (a MediaWiki getting-started
page, a local connector test page, and a stabilization smoke-test file).

The answer was false. The relational store held the fact. Verified read-only
on 2026-11-03:

```text
campaigns.campaigns:              1 row
  campaign_code:                  2026-CRA-IT
  status:                         COMPLETED
  tenant_id:                      cust_0007
campaigns.campaign_companies:     442 rows
```

The data plane existed; the routing never reached it.

### 2.2 Root cause chain (verified 2026-11-03)

1. **Production uses the legacy regex router.**
   `retriva-gateway/src/retriva_gateway/config.py:113` sets
   `AGENT_INTENT_ROUTER_MODE: Literal["off", "shadow", "active"] = "off"`.
   `api/v2/chat.py:96-100` therefore calls
   `IntentDetector.is_crm_workflow(...)`; the deterministic pipeline is
   reached only in `shadow`/`active` (`chat.py:116-127`).
2. **The legacy trigger is a closed vocabulary.**
   `core/intent.py:75` (`_CRM_WORKFLOW`) and `core/intent.py:100`
   (`_CAMPAIGN_COUNT`) are finite regex sets. A phrasing outside them
   becomes `PURE_RAG`. "How many outreach campaigns have we done?" only
   works because the `CAMPAIGN_COUNT` stopgap was added; the general class
   — relational questions phrased as language — remains unserved.
3. **The deterministic engine is closed-world for the same reason.**
   `core/routing/deterministic.py:95-108` lists rule priorities and
   hardcoded vocabularies per intent; `CAMPAIGN_COUNT` is a hand-added rule
   (`deterministic.py:101`, priority 38; rule at `deterministic.py:1461`).
   Every new relational question previously required a new regex, enum
   value, test, and policy entry.
4. **The advisory classifier is too narrow to help.**
   `core/routing/pipeline.py:473` (`eligible_for_classification`) admits only
   two exact ambiguity reason sets; every recognized informational outcome
   is terminal. The Phase D prompt (`retriva-core/src/retriva/intent_classification/prompt.py:29-38`)
   classifies into the same closed intent list with `schema_version "1"`.
   It cannot answer "which data plane?" because that is not its question.

### 2.3 Why the next stopgap is not the answer

The `CAMPAIGN_COUNT` change was a correct immediate fix, but it proves the
failure mode: coverage grows one regex at a time, and the knowledge base
keeps receiving false "insufficient evidence" answers for facts that exist
in PostgreSQL. The fix must move coverage from **regex recall** to
**catalog presence**: if a typed tool exists and is safe to read, the router
can find it without a new vocabulary item.

## 3. Scope

In scope (Phases B–E, each separately gated):

- capability cards derived from the `ToolRegistry` and a module-onboarding
  contract;
- a strict JSON v2 routing contract and prompt v2 on the existing
  `/v1/intent/classification` transport;
- a single gateway call site (`core/routing/semantic.py`);
- read-only loop admission for router-routed turns;
- startup-validated, default-off flags;
- content-free metrics and typed fail-closed behavior;
- an additive eval dataset v2, threshold gates, a shadow run, and an active
  rollout on an isolated synthetic tenant;
- the stopgap freeze.

Out of scope:

- any change to the deterministic safety layer's authority or outcomes;
- writes through the semantic layer (structurally impossible by admission);
- tool-deferred routing / RAG-as-tool (a later, separately gated phase);
- embedding-based pre-routing (documented future cost optimization only);
- RAG ingestion of relational data;
- changes to `retriva-crm-assistant` or `retriva-webui`;
- any production rollout on `cust_0007`;
- enabling any flag by default.

## 4. Ratified decisions (2026-11-03)

These are recorded as **decided**, not as open questions.

- **D-1 — Catalog-driven semantic router.** A routing decision is generated
  from the tool catalog. Capability cards are derived from the
  `ToolRegistry`, which remains the source of truth for routability. The
  deterministic safety layer (commands, negation/hypothetical/quoted
  vetoes, multi-intent, `UNSUPPORTED`, streaming refusal, confirmation
  claims, guards) stays unchanged and terminal.
- **D-2 — Invocation window.** The router sees every non-command turn
  admitted by the exact band in §6 (deterministic safety outcomes remain
  terminal). Deterministic informational rules (documentation framing,
  question anchors) are demoted to router input **hints**. One small-LLM
  call (~0.3–1.5 s) per admitted turn. An embedding pre-gate is a
  documented future cost optimization only.
- **D-3 — Loop admission.** A router-routed turn enters the agent loop with
  the read-only tool subset only (`destructive=False`; the flag already
  exists on every `ToolDefinition`, `agent/tools.py:100`). Writes remain
  reachable only through deterministic command routes. The semantic layer
  can never cause a write, structurally.
- **D-4 — Stopgap freeze.** No new deterministic recall vocabularies are
  added. Existing ones remain fast paths and rollback paths. Coverage gaps
  become capability-card/eval fixes, never regex fixes.
- **D-5 — Growth contract.** Capability cards are a per-module versioned
  artifact derived from each module's tool definitions, with a documented
  module-onboarding contract. A module ships typed tools + a family/topic
  value + its cards + destructive-verb/ID guard declarations + eval
  dataset records; routing coverage follows automatically.
- **D-6 — Out of scope, gated future phase.** Tool-deferred routing /
  RAG-as-tool is not part of this program.
- **D-7 — Governance.** Spec pack + ADR before any code. New flags default
  off. Rollout is `off -> shadow -> active`. Rollback is `mode off` +
  `router flag off`.

### 4.1 Retroactive ratification

`CAMPAIGN_COUNT` (taxonomy enum, `R-CAMPAIGN-COUNT` at priority 38, the
legacy `_CAMPAIGN_COUNT` regex, the `_SAFE_WORKFLOW_INTENTS` entry, and the
`loop.py` prompt guidance) was implemented before this pack under a worker
instruction. ADR-045 ratifies it as a **grandfathered stopgap fast path**
under the freeze policy; it is not removed and not used as a template for
future coverage. This closes the previously unresolved "needs spec/ADR
ratification" item from that worker report.

## 5. Target flow

```text
user message
  |
  +-- deterministic safety layer (UNCHANGED, TERMINAL)
  |     commands, negation / hypothetical / quoted vetoes,
  |     multi-intent, UNSUPPORTED, streaming refusal,
  |     confirmation claims, consequential guards
  |       -> route / refusal / clarify (never overridable)
  |
  +-- deterministic informational rules (DEMOTED TO HINTS)
  |     documentation framing, question anchors
  |       -> categorical hints only (intent, family, reason codes)
  |
  +-- semantic router (ONE small-LLM call, strict JSON v2)
  |       decision = RAG | FAMILY | CLARIFY
  |       RAG    >= threshold -> grounded QA with citations
  |       FAMILY >= threshold -> agent loop, read-only tools only
  |       else / router failure -> fail-closed CLARIFY
  |
  +-- closed, capability-aware deterministic clarification template
        (free-form model text never executes; no tool; no retrieval)
```

The router never sees the message as instructions. It sees the untrusted
message plus categorical hints, and its output is validated by a strict
schema before any route is taken.

## 6. Router input band (exact)

A turn enters the router band when the deterministic engine produces one of:

1. `Intent.RAG_QUESTION`, `Intent.WORKFLOW_DOCUMENTATION`,
   `Intent.STATUS_EXPLANATION`, or `Intent.CAPABILITY_QUESTION` with
   `Explicitness.IMPLICIT`; or
2. `Intent.AMBIGUOUS` that is not already resolved by the Phase C workflow
   context registry.

Every other deterministic outcome is terminal as today: explicit commands,
negation, hypothetical, quoted/example, multi-intent, `UNSUPPORTED`,
streaming refusal, confirmation claims, guard failures, and
`CLARIFICATION_REQUIRED`.

> **Interpretation recorded for Gate A.** The literal band above covers the
> engine's `AMBIGUOUS` outcome. The existing Phase D advisory window also
> covers the workflow-adjacent `CLARIFICATION_REQUIRED` shape; that shape
> is **not** in the Phase C router band and remains terminal (it stays with
> the existing Phase D behavior when that flag is enabled). Expanding the
> band to workflow-adjacent clarification is a pack revision, not a silent
> interpretation. See §13 (D-9) for the resolved hint decision.

## 7. Router output contract (JSON v2)

The router returns exactly one JSON object, validated by a closed pydantic
model (`extra="forbid"`, strict types, strict confidence bounds):

```json
{
  "schema_version": "2",
  "prompt_version": "2",
  "decision": "RAG | FAMILY | CLARIFY",
  "family": "ACP | QUALIFICATION | COMPANY_IMPORT | CAMPAIGN | null",
  "confidence": 0.0,
  "requires_clarification": false,
  "language": "en | it",
  "reason_codes": []
}
```

Closure rules:

- `schema_version` is the literal `"2"`; `prompt_version` is `"2"`.
- `decision` is one of `RAG`, `FAMILY`, `CLARIFY`.
- `family` is `null` for `RAG`/`CLARIFY` and non-null for `FAMILY`.
- The `family` enum is **generated from the capability cards**, not
  hand-written; a family absent from the catalog is invalid.
- `confidence` is a finite number in `[0.0, 1.0]`; NaN/Infinity is invalid.
- `requires_clarification` is `true` exactly for `CLARIFY`.
- `language` is the closed set `en | it`.
- `reason_codes` is a closed set; unknown codes invalidate the output.
- Unknown fields invalidate the output (no permissive parsing).

Invalid output is a router failure, never a permissive route.

## 8. Contracts

### SC1 — Capability cards and module onboarding

- Cards are derived from each module's `ToolRegistry`
  (`agent/tools.py:3759` `get`, `:3762` `names`, `:3765` `openai_schema`).
  There is no hand-written tool list in routing.
- Each card carries, at minimum: `card_id`, `module`, `version`, `family`
  (a `Topic` value), `capability`, `intents`, `tools` (name + type +
  `destructive`), `read_only` (derived), `phrasings` (evaluation metadata
  only), guard declarations, `source` (module/repo), and a
  `digest` (SHA-256 over normalized card content).
- Cards are a **per-module versioned artifact** committed with the module.
  A tool whose `destructive` flag is `true` may still appear on a card,
  but it is never admissible through the semantic router (SC3).
- Onboarding contract: a new module ships typed tools, its family/topic
  value, its cards, destructive-verb/ID guard declarations, and eval
  dataset records. Routing coverage for that module follows automatically;
  no regex is added.
- Derivation and digest tests fail when a tool, schema, or `destructive`
  flag changes without a regenerated card (cards cannot drift from tools).

### SC2 — Schema v2

- The output contract is the closed JSON v2 object in §7.
- Phase B lands the contract in `core/routing/cards.py` (cards and schema
  types); Phase C lands prompt v2 in
  `retriva-core/src/retriva/intent_classification/prompt.py` and the
  gateway validator.
- The Phase D prompt/schema v1 remain valid for the existing advisory
  window. v2 is additive: `prompt_version`/`schema_version` select it.

### SC3 — Invocation and authority

- Exactly **one** gateway call site: `core/routing/semantic.py`.
- Flags are process-global and startup-validated, following the existing
  C7 discipline (`config.py:201-211` style):
  - `AGENT_SEMANTIC_ROUTER_ENABLED` (bool, default `false`);
  - `AGENT_SEMANTIC_ROUTER_MIN_CONFIDENCE` (default `0.85`);
  - `AGENT_SEMANTIC_ROUTER_FAMILY_MIN_CONFIDENCE` (default `0.85`,
    finalized at Gate A 2026-11-03 — D-8);
  - `AGENT_SEMANTIC_ROUTER_TIMEOUT_SECONDS`.
- The router may never route a write. `FAMILY` admission filters the tool
  schema to `ToolDefinition.destructive is False`; writes remain reachable
  only through deterministic command routes.
- The router cannot select a tool, operation, session, tenant, principal,
  KB, or confirmation. It selects a data plane and, for `FAMILY`, a
  catalog family.

### SC4 — Streaming unchanged

- Streaming keeps the deterministic-only gate
  (`pipeline.py:622 classify_streaming_message`): `REFUSE_STREAM`,
  `STREAM_CLARIFY`, or `RAG_PASSTHROUGH`. The semantic router is never
  invoked on a streaming turn.
- **Residual streaming miss class:** a relational read question sent with
  `stream: true` still falls to RAG and may produce the false
  "insufficient evidence" answer. This is documented, not silently fixed.
- The WebUI sends non-streaming chat (`core/models.py:55` `stream = False`;
  `retriva-webui/src/api/gateway-client.ts:161` `sendChatMessage` adds no
  `stream` field), so the production user-facing path is non-streaming.

### SC5 — Failure, privacy, and metrics

- Router failure is **typed and fail-closed**: timeout, unavailable,
  invalid output, schema mismatch, unknown family, or confidence below
  threshold -> deterministic `CLARIFY`. No permissive fallback; no
  secondary model/provider invocation.
- The router receives the untrusted message and categorical hints only:
  no tenant, principal, session, KB, attachment, confirmation, or raw
  workflow-state payloads.
- Metrics are content-free, bounded, and low-cardinality:
  `router_decision_total{decision}`, `router_failure_total{category}`,
  `router_latency`, `router_bypass_total{reason}`. No message text, raw
  model output, identifiers, or prompts are recorded.
- Diagnostics reuse the existing diagnostics-ring privacy rules (Spec 001
  Phase E): categorical fields only.
- **Freeze policy:** no new deterministic recall vocabularies. A
  vocabulary addition is a code-review rejection; coverage gaps are fixed
  in cards or eval records.
- **Interaction matrix:**

  | `AGENT_INTENT_ROUTER_MODE` | `AGENT_SEMANTIC_ROUTER_ENABLED` | Behavior |
  |---|---|---|
  | `off` | any | Exact legacy router; semantic router never invoked |
  | `shadow` | `false` | Spec 001 deterministic pipeline + optional Phase D advisory window; no semantic route change |
  | `shadow` | `true` | Semantic router runs on the band and records shadow diagnostics; the served route remains the Spec 001 deterministic outcome (no semantic route change) |
  | `active` | `false` | Spec 001 deterministic pipeline; Phase D advisory window unchanged |
  | `active` | `true` | Semantic router is authoritative on the band and supersedes the Phase D advisory window for band turns |

## 9. Safety invariants

Each invariant has a named future test. No phase is accepted without it.

1. **No router-routed turn executes a destructive tool.**
   Test: `test_router_routed_turn_never_executes_destructive_tool`.
   Structural: loop admission filters `registry.openai_schema()` to
   `destructive=False`; a destructive tool call is unreachable.
2. **Deterministic safety outcomes are byte-identical to today.**
   Test: `test_deterministic_safety_outcomes_byte_identical`.
   Golden corpus of commands, vetoes, multi-intent, `UNSUPPORTED`,
   confirmation claims, and guard failures.
3. **Failure/timeout/invalid output is a typed fail-closed clarify.**
   Test: `test_router_failure_is_typed_fail_closed_clarify`.
4. **Mode off or router flag off is exact legacy behavior.**
   Test: `test_mode_off_router_disabled_is_exact_legacy`.
   Byte-identical rollback proof at the chat boundary.
5. **Cards are derived from the registry and digest-tested.**
   Test: `test_capability_cards_derived_from_registry_and_digest_matched`.
   No free-text hand-routing; a stale card fails.
6. **The router receives the message and categorical hints only.**
   Test: `test_router_input_is_message_and_categorical_hints_only`.
7. **The freeze is enforced as a code-review rule.**
   Test: `test_frozen_deterministic_recall_vocabulary_unchanged`
   (manifest/digest of the existing vocabularies), plus the review rule.
8. **No recursion in the classification path.**
   Test: `test_classification_path_has_no_tools_no_chat_single_call_site`.
   One call site; no tool registry, no chat completion, no second
   classifier invocation.

## 10. Growth contract (module onboarding)

A module becomes routable without touching the router:

1. it exports typed tools through the shared `ToolDefinition` contract;
2. it declares its family/topic value and card version;
3. it ships derived capability cards (digest-tested);
4. it declares destructive verbs and identifier guards;
5. it adds eval dataset records (paraphrase diversity, EN/IT);
6. the catalog build picks it up; the semantic router's `FAMILY` enum and
   prompt hints are generated.

A module that cannot satisfy these steps is not routable and fails closed to
RAG/CLARIFY. Cards are versioned per module; the catalog version is the
tuple of card versions plus the registry-derived digest.

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Per-turn latency and provider dependency (~0.3–1.5 s) | One call only on the non-command band; timeout typed; fail-closed clarify; embedding pre-gate recorded as a future optimization, not built now. |
| False family routing | Read-only admission makes the worst case a harmless read; KB-vs-DB polysemy pairs in eval v2; confidence band + clarify. |
| Residual misses | Fixed in cards/eval, never regex (D-4). |
| Prompt injection via the message | Preserved v1 untrusted-data framing verbatim; strict SC2 validation; no tools or chat in the classification path; no recursion. |
| Card drift from tools | Derivation + digest tests; stale card fails CI. |
| Shadow/active behavior drift | Mode-off and router-off rollback proof; zero-shadow-route-change gate in Phase D. |
| Confidential-data egress | Reuse the existing internal classification transport and its privacy rules; categorical inputs only; content-free metrics. |
| Streaming gap | Documented residual miss class; WebUI is non-streaming; no silent streaming route change. |

## 12. Numbering and naming (resolved at Gate A, 2026-11-03)

Gate A resolved PENDING-4: this pack uses the project-wide sequence.

- Constitution v1.2 §43 requires **one project-wide numbering sequence**
  for future specifications and one for future ADRs. The requirement
  applies prospectively from v1.2.
- The grandfather clause covers only historical backfills (the
  pre-registry artifacts, including gateway-local `001` / `0001` /
  `0002`). Those keep their original numbers and paths and are not
  renumbered.
- Before this pack the registry's highest allocations were specification
  `039` and ADR `044` (verified 2026-11-03). The next free numbers are
  therefore specification **`040`** and ADR **`045`**.
- The pack was renumbered at Gate A from the provisional gateway-local
  numbers to `040` / `045`. Specification files use zero-padded
  three-digit numbers (`040`); ADR file names use the reserved
  `adr-NNN` prefix (`adr-045-catalog-driven-semantic-routing.md`).

## 13. Resolved owner decisions (Gate A, 2026-11-03)

Gate A is closed. The four previously PENDING questions are resolved as
follows and are normative for Phases B–E.

| ID | Decision (2026-11-03) |
|---|---|
| D-8 (PENDING-1) | Family threshold is **0.85** (`AGENT_SEMANTIC_ROUTER_FAMILY_MIN_CONFIDENCE`). The existing Phase D advisory path keeps **0.90**. Read-only admission bounds the worst case to a harmless read. |
| D-9 (PENDING-2) | Router hints are `last_routed_data_plane` + `last_family` — categorical only, bounded, never raw history — in addition to the existing categorical hints. |
| D-10 (PENDING-3) | Mirrored `AGENT_SEMANTIC_ROUTER_*` flags with distinct authority and independent rollback from the Phase D classifier; the shared Core transport is selected by `prompt_version`. |
| D-11 (PENDING-4) | Renumber to the project-wide sequence: specification **040**, ADR **045**, per Constitution §43 (see §12). |

## 14. Phase gates

| Phase | Deliverable | Gate exit criterion |
|---|---|---|
| A | This pack + ADR-045 + registry entries | **Gate A passed 2026-11-03** (D-8..D-11 resolved); Phase B authorized. |
| B | Cards + schema v2 contracts in `core/routing/cards.py` | Gate B: derivation/digest tests pass; zero behavior change (full gateway baseline unchanged). |
| C | Prompt v2 + `core/routing/semantic.py` + read-only admission + flags + metrics + tests | Gate C: full unit/integration matrix; mode-off byte-identical rollback proof; zero destructive routes. |
| D | Eval dataset v2 + thresholds + shadow run | Gate D: threshold gates pass (including zero-destructive and zero-shadow-route-change); owner reviews the shadow report. |
| E | Active rollout on an isolated synthetic tenant | Gate E: deployed walkthrough + delivery report; `cust_0007` untouched; freeze effective. |

Gate A passed on 2026-11-03. Phase B is authorized. Each subsequent phase
MUST NOT begin before the prior gate passes (Constitution §38).

## 15. References (verified 2026-11-03)

- `retriva-core/.agent/rules/retriva-constitution.md` v1.2: §18 (line 447),
  §38 (line 949), §42 (line 1030), §43 (line 1076).
- `retriva-gateway/src/retriva_gateway/config.py:113` — router mode.
- `retriva-gateway/src/retriva_gateway/api/v2/chat.py:32, 96-100, 116-127,
  606` — routing call site.
- `retriva-gateway/src/retriva_gateway/core/intent.py:75-110, 221, 238` —
  legacy regexes and uses.
- `retriva-gateway/src/retriva_gateway/core/routing/taxonomy.py:136` —
  `CAMPAIGN_COUNT`.
- `retriva-gateway/src/retriva_gateway/core/routing/deterministic.py:95-108,
  101, 1461` — priorities and the stopgap rule.
- `retriva-gateway/src/retriva_gateway/core/routing/pipeline.py:473, 587,
  622` — advisory window and streaming gate.
- `retriva-gateway/src/retriva_gateway/core/routing/policy.py:34, 72, 79,
  87` — thresholds and safe intents.
- `retriva-gateway/src/retriva_gateway/agent/loop.py:158-170` — campaign
  prompt rules.
- `retriva-gateway/src/retriva_gateway/agent/tools.py:89-100, 1499` —
  `ToolDefinition.destructive` and `list_campaigns`.
- `retriva-core/src/retriva/intent_classification/prompt.py:29-38` —
  prompt v1 and schema v1.
- `retriva-core/src/retriva/openai_api/routers/intent_classification.py:17,
  216` — internal classification endpoint.
- `retriva-core/docs/governance/spec-adr-registry.yaml` — registry
  (including the historical gateway-local entries).
- `retriva-gateway/src/retriva_gateway/core/models.py:55` and
  `retriva-webui/src/api/gateway-client.ts:161` — non-streaming chat.
