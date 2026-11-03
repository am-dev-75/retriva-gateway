# Spec 040 — tasks

- **Status:** ACCEPTED (Gate A passed 2026-11-03)
- **Implementation:** Phase B authorized; Phases C–E gated
- **Rule:** check a task only after its evidence is accepted; no task
  bypasses its phase gate.
- **Current slice:** Gate A passed; Phase B implementation is authorized
  and its tasks remain unchecked until Gate B acceptance.

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

## Phase C — semantic router and read-only admission (not started)

- [ ] Add core prompt v2, additive, untrusted framing preserved verbatim.
- [ ] Add `core/routing/semantic.py` as the single call site.
- [ ] Add typed failure categories and fail-closed clarify.
- [ ] Add read-only loop admission (`destructive=False` filter).
- [ ] Add the startup-validated flags (default off/safe).
- [ ] Add content-free `router_*` metrics and bypass reasons.
- [ ] Add the eight named safety-invariant tests.
- [ ] Add the mode-off / flag-off byte-identical rollback proof.
- [ ] **Gate C:** full matrix green; zero destructive routes.

## Phase D — eval dataset v2 and shadow run (not started)

- [ ] Add `dataset-v2.jsonl` and the v2 schema, preserving older datasets.
- [ ] Add EN/IT relational reads for all four families.
- [ ] Add the original miss and informationally framed data questions.
- [ ] Add KB-vs-DB polysemy pairs.
- [ ] Add follow-up reads.
- [ ] Add out-of-catalog questions expected `CLARIFY`.
- [ ] Add adversarial/injection cases.
- [ ] Update `run_evaluation.py` and threshold gates.
- [ ] Add the zero-destructive and zero-shadow-route-change gates.
- [ ] Run the shadow mode and produce the shadow report.
- [ ] **Gate D:** owner reviews the shadow report.

## Phase E — active rollout and freeze (not started)

- [ ] Enable active mode on the isolated synthetic tenant only.
- [ ] Run the deployed walkthrough.
- [ ] Produce the delivery report.
- [ ] Make the stopgap freeze effective.
- [ ] **Gate E:** owner accepts the walkthrough and delivery report.
