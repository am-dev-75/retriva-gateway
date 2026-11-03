# ADR-045: Catalog-Driven Semantic Router for Retriva Chat Routing

- **Status:** ACCEPTED (Gate A passed 2026-11-03; Phase B authorized)
- **Date:** 2026-11-03 (Gate A: 2026-11-03)
- **Deciders:** Retriva owner (ratified program 2026-11-03), Kilo (code agent)
- **Scope:** `retriva-gateway` (routing, agent-loop admission);
  `retriva-core` (additive prompt/schema v2 on the existing internal
  classification endpoint)
- **Spec pack:** `retriva-gateway/specs/040-catalog-driven-semantic-routing/`
- **Governing authority:** `retriva-core/.agent/rules/retriva-constitution.md`
  v1.2, §§ 18, 38, 42, 43
- **Extends, does not amend:** Spec 001 / ADR-0002 (hybrid intent routing;
  deterministic safety layer and advisory classifier). The deterministic
  safety layer remains unchanged and terminal.
- **Implementation:** Phase B authorized; Phases C–E gated.

## Context

Retriva routes chat between grounded, cited RAG and the relational Company
Intelligence data plane. Production runs the legacy regex router
(`retriva-gateway/src/retriva_gateway/config.py:113`,
`AGENT_INTENT_ROUTER_MODE="off"`; `api/v2/chat.py:96-100` calls
`IntentDetector.is_crm_workflow`; `core/intent.py:75-110`). The
deterministic engine (`core/routing/deterministic.py`) is closed-world and
hand-maintained; the advisory classifier
(`core/routing/pipeline.py:473 eligible_for_classification`) is limited to
two exact ambiguity reason sets, and the core prompt
(`retriva-core/src/retriva/intent_classification/prompt.py:29-38`)
classifies into the same closed intent list.

On 2026-11-02 the production chat answered "How many outreach campaigns
have we done?" with a false "insufficient evidence" RAG answer, citing
three irrelevant documents. The relational store held the fact: one
`COMPLETED` campaign (`2026-CRA-IT`, tenant `cust_0007`, 442 memberships;
verified read-only 2026-11-03). The failure is routing coverage, not data
availability.

`CAMPAIGN_COUNT` was added as a stopgap
(`core/routing/taxonomy.py:136`;
`core/routing/deterministic.py:101`, priority 38; rule at
`deterministic.py:1461`; legacy regex `core/intent.py:100`;
`core/routing/policy.py:87`; prompt guidance `agent/loop.py:158-170`).
It fixes that phrasing but repeats the failure mode: every new relational
question needs a new regex, enum value, policy entry, and test.

The tool catalog already knows what is routable. Each module registers typed
`ToolDefinition`s (`agent/tools.py:89`) with a `destructive` flag
(`agent/tools.py:100`). The router should read the catalog, not a vocabulary.

## Decision

The owner-ratified program (2026-11-03) is recorded as seven decisions:

1. **Catalog-driven semantic router.** The routing decision is generated
   from capability cards derived from the `ToolRegistry`, the source of
   truth for routability. The deterministic safety layer (commands,
   negation/hypothetical/quoted vetoes, multi-intent, `UNSUPPORTED`,
   streaming refusal, confirmation claims, guards) stays unchanged and
   terminal.
2. **Invocation window.** The router sees every non-command turn.
   Deterministic informational rules (documentation framing, question
   anchors) are demoted to router input hints. Deterministic safety
   outcomes stay terminal. One small-LLM call (~0.3–1.5 s) per non-command
   turn. An embedding pre-gate is documented as a future cost optimization
   only.
3. **Loop admission.** Router-routed turns enter the agent loop with the
   read-only tool subset only (`destructive=False`). Writes remain
   reachable only through deterministic command routes, so the semantic
   layer can never cause a write, structurally.
4. **Stopgap freeze.** No new deterministic recall vocabularies. Existing
   ones stay as fast paths and rollback paths. Coverage gaps become
   capability-card/eval fixes, never regex fixes.
5. **Growth contract.** Capability cards are a per-module versioned
   artifact derived from each module's tool definitions. A module ships
   typed tools + a family/topic value + its cards + destructive-verb/ID
   guard declarations + eval dataset records; routing coverage follows
   automatically.
6. **Out of scope, gated future phase.** Tool-deferred routing /
   RAG-as-tool is not part of this program.
7. **Governance.** Spec pack + ADR before any code; new flags default off;
   rollout off -> shadow -> active; rollback = mode off + router flag off.

The target flow, the exact router input band, the strict JSON v2 contract,
contracts SC1–SC5, the eight safety invariants, and the phase gates are
normative in the spec pack.

## Cost model

- One small-LLM call per non-command turn, approximately 0.3–1.5 s,
  bounded by an HTTP timeout and typed fail-closed behavior.
- The call happens only inside the router band; deterministic commands and
  safety outcomes cost nothing.
- A single call per turn; no retries that re-invoke a model/provider; no
  secondary fallback model.
- An embedding pre-gate is documented as a future cost optimization only,
  not built in Phases B–E. It would reduce call volume at the cost of a new
  local model dependency and is therefore deferred.
- Metrics (`router_*`) are content-free and low-cardinality so the cost is
  observable without new privacy exposure.

## Read-only admission rationale

The semantic router is an untrusted language model. The safest structural
bound is to make a misroute harmless:

- `FAMILY` routes enter the agent loop with a schema filtered to
  `ToolDefinition.destructive is False`;
- destructive tools remain reachable only through the deterministic command
  routes and their existing guards;
- the router cannot select a tool, operation, resource, identity, session,
  confirmation, or write;
- a router-routed turn therefore cannot mutate Company Intelligence even if
  the model is wrong, adversarially prompted, or compromised.

This is a structural invariant, not a prompt instruction. It is proved by
`test_router_routed_turn_never_executes_destructive_tool`.

## The freeze

No new deterministic recall vocabularies are added after this pack. This
applies to regexes, intent enum values added for recall, safe-workflow
policy entries added for recall, and prompt tool-list guidance added for
recall. Existing vocabularies are grandfathered fast paths and rollback
paths.

Coverage gaps are fixed in:

- capability cards (a tool exists but its card/phrasing dataset is
  incomplete), or
- the eval dataset (a paraphrase was not represented).

They are never fixed by adding a regex. The freeze is enforceable in
review and is covered by
`test_frozen_deterministic_recall_vocabulary_unchanged`.

## Retroactive ratification — CAMPAIGN_COUNT

`CAMPAIGN_COUNT` was implemented on 2026-11-03 (commit
`350c6f3 feat(gateway): route campaign count questions through CRM tools`)
under a worker instruction, **before** this governance pack existed. It is
hereby ratified as a **grandfathered stopgap fast path** under the freeze
policy. The ratified artifact set is:

| Artifact | Location |
|---|---|
| Taxonomy enum | `core/routing/taxonomy.py:136` |
| Deterministic rule | `core/routing/deterministic.py:101` (priority 38), `:1461` |
| Legacy regex | `core/intent.py:100` |
| Safe-workflow policy | `core/routing/policy.py:87` |
| Prompt tool-list guidance | `agent/loop.py:158-170` |

It remains a fast path and rollback path. It is not a template for future
coverage, and it is not removed by this pack. This ratification closes the
previously unresolved "needs spec/ADR ratification" item from the worker
report, subject to Gate A owner acceptance of this ADR.

## Consequences

Positive:

- New relational questions are covered by catalog presence, not new regex.
- Misroutes are structurally limited to reads.
- The deterministic safety layer remains the authority.
- Coverage is testable through cards and eval data.
- Rollback is a two-flag operation with no data migration.

Negative / accepted:

- One small-LLM call on the non-command band adds latency and provider
  dependency.
- The router band initially excludes workflow-adjacent
  `CLARIFICATION_REQUIRED`; expanding it is a pack revision.
- Streaming keeps the residual miss class; the WebUI is non-streaming.
- Cards must be regenerated when tools change; the digest test fails
  otherwise (a deliberate cost).

Neutral:

- The Phase D advisory window remains for out-of-band turns; the semantic
  router supersedes it only on the band when enabled.
- No schema, migration, or RAG-ingestion change.

## Rejected alternatives

1. **Continue stopgap regexes.** Rejected: it is the failure mode itself.
   Every new relational question needs another vocabulary item, the
   knowledge base keeps giving false insufficiency answers, and coverage
   is not derived from what the system can actually do.
2. **Tool-deferred routing now (RAG-as-tool).** Rejected for this program:
   it changes the answering architecture (the model decides when to call a
   data tool inside RAG), broadens the injection surface, and is a larger,
   separately gated change. D-6 keeps it as a future phase.
3. **Embedding pre-router now.** Rejected for Phases B–E: it adds a local
   model, index, and threshold surface before the catalog router works.
   It is recorded as a future cost optimization only.
4. **Let the router select tools or operations directly.** Rejected: it
   would make an LLM an authorization mechanism and could reach writes.
   The router selects a data plane/family only; the loop selects from the
   read-only subset.

## Resolved owner decisions (Gate A, 2026-11-03)

1. **D-8 (PENDING-1) — family threshold.** `0.85` for read-only family
   routing; `0.90` retained for the existing safe-workflow advisory path.
   Read-only admission bounds the worst case to a harmless read.
2. **D-9 (PENDING-2) — hint set.** Add `last_routed_data_plane` and
   `last_family` categorical hints for read follow-ups (categorical only,
   bounded, never raw history).
3. **D-10 (PENDING-3) — transport flags.** Mirrored
   `AGENT_SEMANTIC_ROUTER_*` flags with distinct authority and independent
   rollback from the Phase D classifier; the shared Core transport is
   selected by `prompt_version`.
4. **D-11 (PENDING-4) — naming.** Renumber to the project-wide sequence:
   specification `040`, ADR `045`, per Constitution §43 (one project-wide
   sequence, prospective from v1.2; the grandfather clause covers only
   historical backfills).

## References

- `retriva-gateway/specs/040-catalog-driven-semantic-routing/spec.md`
- `retriva-gateway/specs/040-catalog-driven-semantic-routing/architecture.md`
- `retriva-gateway/specs/040-catalog-driven-semantic-routing/acceptance.md`
- `retriva-gateway/docs/adr/0002-hybrid-intent-routing.md`
- `retriva-core/.agent/rules/retriva-constitution.md` v1.2 §§ 18, 38, 42, 43
- `retriva-core/docs/governance/spec-adr-registry.yaml`
