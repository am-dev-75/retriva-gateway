# Spec 040 — tasks

- **Status:** ACCEPTED (Gate A passed 2026-11-03)
- **Implementation:** Phases B–E implemented; Phase E active (owner
  authorized 2026-11-06)
- **Rule:** check a task only after its evidence is accepted; no task
  bypasses its phase gate.
- **Current slice:** Gate D PASSED 2026-11-06; active rollout executed.
  Gate E delivery acceptance remains with the owner.

## Execution record — Phase C/D (2026-11-06)

- **Incident root cause:** the Italian addressed-companies question had no
  matching deterministic rule; the `CAMPAIGN_COUNT` window over-matched
  it, and production mode `off` kept it on RAG. The over-broad window was
  narrowed (freeze-compliant bug fix, no new vocabulary).
- **Capability growth:** added the read-only
  `get_campaign_company_stats` campaign tool (cards auto-derive).
- **Phase C:** Core prompt/schema v2 on the existing internal endpoint;
  Gateway `core/routing/semantic.py` single call site; exact input band;
  SC2 validation; 0.85/0.85 thresholds; read-only loop admission; typed
  fail-closed clarify; content-free `router_*` metrics; startup-validated
  default-off flags.
- **Gate C verification:** Gateway 932 passed with only the 3 known
  pre-existing failures; Core 1169 passed (22 new) with the documented
  pre-existing environment failures unchanged (before/after node
  comparison).
- **Phase D shadow:** dataset v2 (24 records), shadow runner and gates;
  incident classified FAMILY/CAMPAIGN at confidence 1.0 while the served
  route stayed CLARIFY; 20/20 decision accuracy; zero destructive
  executions; zero router-routed tool calls; zero shadow route changes.
- **Gate D (2026-11-06):** PASSED. The owner reviewed the shadow evidence
  package (20/20 router decision accuracy, zero destructive executions,
  zero router-routed tool calls, zero shadow route changes; incident
  question FAMILY/CAMPAIGN at confidence 1.0) and authorized active rollout
  in a controlled environment.
- **Phase E (2026-11-06):** EXECUTED. Runtime moved to
  `AGENT_INTENT_ROUTER_MODE=active` with
  `AGENT_SEMANTIC_ROUTER_ENABLED=true` (`.env` change 11:38–11:39 +01;
  gateway container created 2026-11-06T14:29:00Z), thresholds 0.85/0.85.
  Rollback remains `mode=off` + router flag off.
- **Post-rollout evidence:** the Italian campaign-export clarify of
  2026-11-06 is recorded in `docs/semantic-routing.md` as production
  evidence; its localization/export remediation is tracked separately.

## Phase A — governance (this turn)

- [x] Re-verify every audit citation against the working tree
  (2026-11-03).
- [x] Record the production evidence (1 COMPLETED campaign, 2026-CRA-IT,
  tenant `cust_0007`, 442 memberships).
- [x] Write the spec pack (`spec.md`, `architecture.md`, `plan.md`,
  `tasks.md`, `acceptance.md`).
- [x] Write ADR-045 with the seven ratified decisions, cost model,
  read-only admission, freeze, and rejected alternatives.
- [x] Ratify the `CAMPAIGN_COUNT` stopgap as a grandfathered fast path.
- [x] Record the four owner questions; resolved at Gate A as D-8..D-11.
- [x] Allocate project-wide specification `040` and ADR `045` in the
  core registry with status `accepted`.
- [x] Verify the registry parses and the registry-integrity test passes.
- [x] Verify the gateway baseline is unchanged (829 passed, 3 known
  pre-existing unrelated failures).
- [x] **Gate A:** owner accepted the pack on 2026-11-03; PENDING-1..4
  resolved as D-8..D-11 (Spec §13); Phase B authorized.

## Phase B — capability cards and schema v2 (authorized at Gate A)

- [ ] Add `core/routing/cards.py`: card types, derivation, normalized
  digests, catalog version.
- [ ] Generate the `FAMILY` enum from the card catalog.
- [ ] Add the SC2 pydantic model (`extra="forbid"`, strict confidence,
  cross-field rules).
- [ ] Add derivation and digest tests (registry is the only source).
- [ ] Add the stale-card failure test (tool/schema/`destructive` drift).
- [ ] Prove zero behavior change; full baseline green.
- [ ] **Gate B:** owner accepts cards + contracts.

## Phase C — semantic router and read-only admission (implemented)

- [ ] Add core prompt v2, additive, untrusted framing preserved verbatim.
- [ ] Add `core/routing/semantic.py` as the single call site.
- [ ] Add typed failure categories and fail-closed clarify.
- [ ] Add read-only loop admission (`destructive=False` filter).
- [ ] Add the startup-validated flags (default off/safe).
- [ ] Add content-free `router_*` metrics and bypass reasons.
- [ ] Add the eight named safety-invariant tests.
- [ ] Add the mode-off / flag-off byte-identical rollback proof.
- [ ] **Gate C:** full matrix green; zero destructive routes.

## Phase D — eval dataset v2 and shadow run (Gate D passed 2026-11-06)

- [x] Add `dataset-v2.jsonl` and the v2 schema, preserving older datasets.
- [x] Add EN/IT relational reads for all four families.
- [x] Add the original miss and informationally framed data questions.
- [x] Add KB-vs-DB polysemy pairs.
- [x] Add follow-up reads.
- [x] Add out-of-catalog questions expected `CLARIFY`.
- [x] Add adversarial/injection cases.
- [x] Update `run_evaluation.py` and threshold gates.
- [x] Add the zero-destructive and zero-shadow-route-change gates.
- [x] Run the shadow mode and produce the shadow report.
- [x] **Gate D:** owner reviewed the shadow report and authorized active
  rollout on 2026-11-06.

## Phase E — active rollout and freeze (executed 2026-11-06)

- [x] Enable active mode (owner-authorized controlled environment).
- [x] Run the deployed walkthrough.
- [x] Produce the delivery report (`docs/semantic-routing-delivery.md`).
- [x] Make the stopgap freeze effective.
- [ ] **Gate E:** owner accepts the walkthrough and delivery report.
