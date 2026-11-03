# Spec 040 — architecture

- **Status:** ACCEPTED (Gate A passed 2026-11-03)
- **Companion ADR:** ADR-045
- **Implementation:** Phase B authorized; Phases C–E gated

## 1. Component map

```text
retriva-gateway
  api/v2/chat.py
    -> _run_agent_mode(request)
         mode off  -> core/intent.py IntentDetector (legacy; unchanged)
         shadow/active
           -> core/routing/pipeline.py route_non_streaming()
                -> core/routing/deterministic.py (safety layer; TERMINAL)
                -> [Phase C] core/routing/semantic.py (single call site)
                     -> core/routing/cards.py (catalog + schema v2)
                     -> core/routing/classifier.py transport
                          -> retriva-core
                               POST /v1/intent/classification
                                 prompt v1 (Phase D, unchanged)
                                 prompt v2 (Phase C, additive)
           -> bounded agent loop (agent/loop.py)
                -> read-only schema subset (destructive=False)
                     when the turn was FAMILY-routed

retriva-core
  src/retriva/intent_classification/prompt.py   prompt v1 + v2
  src/retriva/openai_api/routers/intent_classification.py
                                               existing internal endpoint
```

There is exactly one semantic-router call site in the gateway. The
classification path has no tool registry access, no chat completion, and no
second classifier call (invariant 8).

## 2. Deterministic safety layer (unchanged, terminal)

The following outcomes are produced by the existing deterministic engine and
are never overridden by the semantic router:

- explicit commands and their consequential guards;
- negation, hypothetical, quoted/example, prompt-writing vetoes;
- multi-intent;
- `UNSUPPORTED` / unavailable vocabulary;
- streaming refusal and streaming clarification;
- confirmation claims;
- guard failures (`GUARD_RESOURCE_UNRESOLVED`);
- `CLARIFICATION_REQUIRED` (all reason sets).

The engine and its rule priorities remain the authority. `CAMPAIGN_COUNT`
(`deterministic.py:101`, priority 38; rule `deterministic.py:1461`) stays a
fast path and rollback path, and is grandfathered under the freeze.

## 3. Router input band and demoted hints

The band is exactly the one defined in `spec.md` §6. In `shadow`/`active`
mode, the deterministic informational outcomes are no longer terminal; they
become **hints**:

- `intent` and `family` from the deterministic result;
- the closed `reason_codes`;
- the detected language;
- optional session-derived categorical hints (D-9):
  `last_routed_data_plane`, `last_family`.

Hints are categorical only. The message is passed verbatim as untrusted
data, never as instructions. No tenant, principal, session, KB,
attachment, confirmation, or raw workflow payload is sent.

## 4. Capability cards (SC1)

### 4.1 Source of truth

`agent/tools.py` is authoritative:

- `ToolDefinition` (`:89`) with `destructive: bool = False` (`:100`);
- `ToolRegistry.get/names/openai_schema` (`:3759`, `:3762`, `:3765`);
- every module's registered tool definitions (e.g. `list_campaigns` at
  `:1499`, read-only by default).

No routing code may hand-write a tool list.

### 4.2 Card shape

```yaml
card_id: campaign.read
module: retriva-gateway/campaign-governance
version: 1
family: CAMPAIGN
capability: campaign.read.list
intents: [CAMPAIGN_STATUS, CAMPAIGN_COUNT]
read_only: true
tools:
  - name: list_campaigns
    destructive: false
    schema_digest: <sha256>
  - name: get_campaign
    destructive: false
    schema_digest: <sha256>
phrasings:            # evaluation metadata only; never routing vocabulary
  - "How many outreach campaigns have we done?"
  - "Quante campagne abbiamo fatto?"
guards:
  destructive_verbs: [create, commit, approve, activate, revoke]
  id_patterns: [campaign:camp_*, import:ibth_*]
source:
  repository: retriva-gateway
  tool_registry: agent/tools.py
digest: <sha256 over normalized card content>
```

`read_only` is derived (all listed tools have `destructive=False`). A card
may document destructive tools, but they are never admissible through the
semantic router.

### 4.3 Derivation and digest tests

- `cards == derive_cards(build_default_tool_registry())`, normalized.
- Card `digest` equals the recomputed digest.
- Adding/removing a tool, changing its parameter schema, or flipping
  `destructive` without regenerating the card fails the test.
- The `FAMILY` enum in schema v2 is generated from the union of card
  families, sorted deterministically.

### 4.4 Module onboarding

A module ships: typed tools, family/topic value, cards, destructive-verb/ID
guard declarations, and eval records. The catalog build then includes it.
No router code change and no regex.

## 5. Schema v2 (SC2)

Phase B lands `core/routing/cards.py` with:

- the pydantic model (`extra="forbid"`, strict types);
- `schema_version: Literal["2"]`, `prompt_version: Literal["2"]`;
- `decision: Literal["RAG", "FAMILY", "CLARIFY"]`;
- a generated `Family` enum;
- `confidence: float` with `ge=0.0, le=1.0, allow_inf_nan=False`;
- `requires_clarification: bool`;
- `language: Literal["en", "it"]`;
- `reason_codes: list[ClosedReasonCode]`;
- a model validator enforcing the cross-field rules in `spec.md` §7.

Phase C adds prompt v2 to the same packaged prompt module. The v1 prompt and
schema remain for the Phase D advisory window; the version fields select the
contract.

## 6. Invocation and authority (SC3)

### 6.1 One call site

`core/routing/semantic.py` exposes:

```python
async def route_semantic(
    *,
    message: str,
    hints: RouterHints,
    cards: CapabilityCatalog,
    config: SemanticRouterConfig,
) -> SemanticRoute:
    ...
```

It is called once from the pipeline's band decision. It never calls the
agent loop, tools, or chat completion.

### 6.2 Flags

Process-global, startup-validated (same discipline as
`config.py:201-211`):

| Flag | Default | Validation |
|---|---|---|
| `AGENT_SEMANTIC_ROUTER_ENABLED` | `false` | bool |
| `AGENT_SEMANTIC_ROUTER_MIN_CONFIDENCE` | `0.85` | `[0.50, 1.00]` |
| `AGENT_SEMANTIC_ROUTER_FAMILY_MIN_CONFIDENCE` | `0.85` | `[0.50, 1.00]` and `>= MIN_CONFIDENCE` |
| `AGENT_SEMANTIC_ROUTER_TIMEOUT_SECONDS` | implementation-defined | positive, bounded |

The family default was finalized at Gate A 2026-11-03 as `0.85` (D-8). No
per-request, tenant, session, or model override exists.

### 6.3 Authority

- `RAG` -> the existing grounded QA path with citations.
- `FAMILY` -> the bounded agent loop with the **read-only** schema subset.
- `CLARIFY` -> the closed, capability-aware deterministic template.
- Router failure -> `CLARIFY`.

The router cannot select an operation, tool, resource, identity, or
confirmation. Writes remain reachable only through deterministic command
routes.

## 7. Read-only loop admission (D-3)

Admission composes the existing registry:

```text
allowed = settings.AGENT_TOOL_ALLOWLIST or None
schema  = registry.openai_schema(allowed)
schema  = [t for t in schema if registry.get(t.name).destructive is False]
```

The loop receives only the filtered schema. Executor-side defense remains:
if a destructive tool name somehow reaches `_execute_tool`, the registry
lookup can reject it before execution (defense in depth; the structural
filter is the primary proof).

Invariant 1 is proved by a dedicated test that plants a destructive tool
call in a router-routed turn and asserts it never executes.

## 8. Streaming (SC4)

Streaming is **unchanged**:

- `classify_streaming_message` (`pipeline.py:622`) remains deterministic-only.
- `_STREAM_WORKFLOW_INTENTS` (`pipeline.py:587`) and the adjacent-class logic
  are untouched.
- The semantic router is never called with `stream=true`.

Residual miss class: a relational read question sent with streaming still
falls to RAG and can produce the false insufficiency answer. This is
documented. The WebUI sends non-streaming chat (`core/models.py:55`;
`retriva-webui/src/api/gateway-client.ts:161`).

## 9. Failure, privacy, and metrics (SC5)

### 9.1 Fail-closed categories

| Category | Cause | Outcome |
|---|---|---|
| `router_disabled` | flag off (not a failure) | existing behavior |
| `router_timeout` | HTTP timeout | `CLARIFY` |
| `router_unavailable` | transport/5xx/auth failure | `CLARIFY` |
| `router_invalid_output` | schema violation / unknown field | `CLARIFY` |
| `router_schema_mismatch` | version not `"2"` | `CLARIFY` |
| `router_unknown_family` | family not in cards | `CLARIFY` |
| `router_below_threshold` | confidence under the plane threshold | `CLARIFY` |

There is no permissive fallback and no second model/provider call.

### 9.2 Privacy

Input: untrusted message + categorical hints only. Output: validated closed
JSON. Logs/metrics: content-free. Diagnostics reuse the existing
diagnostics-ring privacy rules. Prompts, messages, raw model output,
identifiers, and credentials are never logged.

### 9.3 Metrics

- `router_decision_total{decision}`;
- `router_failure_total{category}`;
- `router_latency`;
- `router_bypass_total{reason}`.

Closed, bounded, low-cardinality labels. Unknown values raise at call time
(same discipline as the existing routing metrics).

### 9.4 Interaction matrix

See `spec.md` §8 SC5. Summary:

- mode `off`: exact legacy; router never invoked.
- mode `shadow`, flag `false`: Spec 001 pipeline; Phase D window unchanged.
- mode `shadow`, flag `true`: the router runs and records shadow diagnostics;
  the served route remains the Spec 001 deterministic outcome (no semantic
  route change).
- mode `active`, flag `false`: Spec 001 pipeline; Phase D window unchanged.
- mode `active`, flag `true`: router authoritative on the band; supersedes
  the Phase D advisory window for band turns.

## 10. Rollout and rollback

```text
off  -> shadow -> active
```

- `off`: `AGENT_INTENT_ROUTER_MODE=off` (and flag irrelevant) — exact legacy.
- `shadow`: mode `shadow`, flag `true` — router decisions recorded, route
  outcome governed by the Phase C shadow rule; no user-visible change.
- `active`: mode `active`, flag `true` — router authoritative on the band.
- Rollback: mode `off` **and** flag `false`. Both steps are required by
  D-7; each alone is also a valid narrower rollback.

## 11. Invariant-to-test map

| # | Invariant | Phase C test |
|---|---|---|
| 1 | no destructive tool on a router turn | `test_router_routed_turn_never_executes_destructive_tool` |
| 2 | safety outcomes byte-identical | `test_deterministic_safety_outcomes_byte_identical` |
| 3 | typed fail-closed clarify | `test_router_failure_is_typed_fail_closed_clarify` |
| 4 | mode off / flag off exact legacy | `test_mode_off_router_disabled_is_exact_legacy` |
| 5 | cards derived + digest | `test_capability_cards_derived_from_registry_and_digest_matched` |
| 6 | message + categorical hints only | `test_router_input_is_message_and_categorical_hints_only` |
| 7 | freeze rule | `test_frozen_deterministic_recall_vocabulary_unchanged` |
| 8 | no recursion | `test_classification_path_has_no_tools_no_chat_single_call_site` |

## 12. Deployment and data notes

- No schema or migration change.
- No RAG ingestion of relational data.
- Reuse the existing internal classification transport and its service
  credential, purpose marker, size/rate/concurrency limits, and timeout.
- No change to `retriva-crm-assistant` or `retriva-webui`.
- `cust_0007` is never used for rollout; Phase E uses an isolated synthetic
  tenant.

## 13. Open architecture assumptions

- The card artifact location (`core/routing/cards.py` plus per-module data)
  is finalized in Phase B; the derivation and digest contract is normative
  now.
- Whether the router band later expands to workflow-adjacent
  `CLARIFICATION_REQUIRED` is a pack revision (see `spec.md` §6 note).
- The family threshold default is `0.85` (D-8); the architecture also
  permits `0.90` without structural change.
