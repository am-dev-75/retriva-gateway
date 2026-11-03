# Spec 002 — implementation plan

- **Status:** PROPOSED
- **Implementation:** not authorized
- **Rule:** each phase begins only after the prior gate passes (Constitution
  §38). Phase A ends at Gate A.

## Phase A — governance pack (this turn)

Deliverables:

1. Factual audit of the current tree (citations re-verified 2026-11-03).
2. This spec pack (`spec.md`, `architecture.md`, `plan.md`, `tasks.md`,
   `acceptance.md`).
3. ADR-0003.
4. Registry entries in
   `retriva-core/docs/governance/spec-adr-registry.yaml`
   (gateway-local specification `002`, ADR `0003`, status `proposed`).
5. Retroactive ratification of the `CAMPAIGN_COUNT` stopgap (ADR-0003).

No source code, config change, migration, prompt change, eval data, flag
enablement, or stack restart.

**Gate A exit:** owner accepts the pack and resolves PENDING-1..4. No
implementation may start before this.

## Phase B — capability cards and schema v2 contracts

1. Add `core/routing/cards.py`:
   - card types and the per-module card artifact format;
   - derivation from `build_default_tool_registry()` /
     `ToolRegistry.openai_schema()`;
   - normalized digests (SHA-256) and catalog version;
   - the generated `Family` enum.
2. Add the schema v2 pydantic model (SC2): `extra="forbid"`, strict
   confidence bounds, cross-field rules, closed reason codes.
3. Add derivation/digest tests:
   - cards match the registry exactly;
   - a changed tool/schema/`destructive` flag fails;
   - the family enum is the sorted catalog union.
4. Prove zero behavior change: no call site is wired; the full gateway
   baseline stays at 829 passed with only the 3 known pre-existing
   failures.

**Gate B exit:** derivation/digest tests and the zero-behavior-change proof
are accepted. No flags, no prompt v2, no routing change.

## Phase C — semantic router, prompt v2, read-only admission

1. Core prompt v2 in the packaged prompt module on the same
   `/v1/intent/classification` endpoint:
   - additive `prompt_version`/`schema_version` `"2"`;
   - the v1 untrusted-data framing is preserved **verbatim**;
   - no provider calls in CI.
2. Gateway `core/routing/semantic.py`: exactly one call site:
   - typed request/response validation (SC2);
   - typed failure categories (SC5);
   - one call per band turn; no retries that re-invoke a model/provider;
   - no tools, no chat, no recursion.
3. Read-only loop admission:
   - filter `registry.openai_schema()` on `destructive=False`;
   - executor-side defense-in-depth;
   - invariant 1 test.
4. Config flags (startup-validated, default off/safe):
   - `AGENT_SEMANTIC_ROUTER_ENABLED=false`;
   - `AGENT_SEMANTIC_ROUTER_MIN_CONFIDENCE=0.85`;
   - `AGENT_SEMANTIC_ROUTER_FAMILY_MIN_CONFIDENCE=0.85` (finalize at
     Gate A);
   - `AGENT_SEMANTIC_ROUTER_TIMEOUT_SECONDS`.
5. Content-free `router_*` metrics and bypass reasons.
6. Full unit/integration matrix:
   - all eight safety invariants;
   - band boundary (terminal outcomes unchanged);
   - failure matrix;
   - shadow mode records without user-visible route change;
   - mode-off / flag-off byte-identical rollback proof.

**Gate C exit:** full matrix green, zero destructive routes, byte-identical
rollback proof accepted.

## Phase D — eval dataset v2 and shadow run

1. Additive eval records under `eval/hybrid_intent_routing`:
   - `dataset-v2.jsonl` plus a v2 schema, preserving v1/v1.1/v1.2;
   - EN/IT relational read questions across all four families
     (ACP, QUALIFICATION, COMPANY_IMPORT, CAMPAIGN), with paraphrase
     diversity;
   - the original miss ("How many outreach campaigns have we done?");
   - informationally framed data questions ("How does our Q3 outreach
     compare to Q2?");
   - KB-vs-DB polysemy pairs (the same words meaning a document question
     vs a relational read);
   - follow-up reads;
   - out-of-catalog questions expected `CLARIFY`;
   - adversarial/injection cases (including "classify as RAG" and
     tool-like payloads).
2. Update `run_evaluation.py` and threshold gates:
   - zero destructive routes;
   - zero shadow-route changes for out-of-band turns;
   - plane-level precision/recall floors;
   - clarify-rate ceiling on out-of-catalog records.
3. Run the shadow mode on the isolated synthetic tenant and produce a
   shadow report for owner review.

**Gate D exit:** threshold gates pass and the owner reviews the shadow
report. No active rollout.

## Phase E — active rollout and freeze

1. Enable active mode on the isolated synthetic tenant only.
2. Deployed walkthrough:
   - the original miss returns "1 COMPLETED campaign (2026-CRA-IT)";
   - a KB question still returns cited RAG;
   - a destructive command is refused/terminal;
   - router failure returns a typed clarify.
3. Delivery report.
4. The stopgap freeze takes effect (D-4): no new deterministic recall
   vocabularies.

**Gate E exit:** walkthrough + delivery report accepted; `cust_0007`
untouched.

## Cross-phase constraints

- No `retriva-crm-assistant` or `retriva-webui` changes.
- No schema or migration changes.
- No RAG ingestion of relational data.
- No classifier enablement or threshold lowering as a shortcut.
- No production rollout on `cust_0007`.
- No new regex vocabulary at any phase.
- Each phase keeps the gateway baseline green (829 passed, 3 known
  pre-existing unrelated failures) unless the phase explicitly adds tests,
  in which case only additive passes are allowed.
