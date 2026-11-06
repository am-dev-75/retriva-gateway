# Spec 040 — acceptance contract

- **Status:** ACCEPTED (Gate A passed 2026-11-03)
- **Phase A environment:** documentation only; no runtime change
- **Prohibition:** never mutate `cust_0007` or production state
- **Implementation:** Phase B authorized; Phases C–E gated

## 1. Gate A — owner acceptance of the pack

Gate A required:

1. The owner accepts `spec.md`, `architecture.md`, `plan.md`, `tasks.md`,
   and this acceptance contract.
2. The owner accepts ADR-045.
3. The registry entries (`040`, `045`) are present, parse cleanly, and
   point at existing artifacts.
4. PENDING-1..4 resolved at Gate A (2026-11-03) as D-8..D-11:
   - D-8: family threshold `0.85`; `0.90` retained for the Phase D
     advisory path.
   - D-9: hints `last_routed_data_plane` + `last_family` (categorical
     only, bounded, never raw history).
   - D-10: mirrored `AGENT_SEMANTIC_ROUTER_*` flags with independent
     rollback; shared Core transport selected by `prompt_version`.
   - D-11: renumbered to project-wide specification `040` / ADR `045`.
5. No source, config, migration, prompt, eval, or flag change is part of
   Phase A.

**Gate A result (2026-11-03): PASSED.** The owner accepted the pack and
resolved all four questions; Phase B is authorized. Phases C–E remain
gated on their own phase acceptance.

## 2. Phase A verification evidence

Run from `retriva-gateway`:

```text
PYTHONPATH=src .venv/bin/python -m compileall -q src tests
PYTHONPATH=src .venv/bin/python -m pytest tests -q
```

Required result:

- `compileall` exits 0;
- `829 passed`, with only these 3 known pre-existing unrelated failures:
  - `tests/test_gateway.py::test_kbs_list_translates_core_response_to_webui_shape`
  - `tests/test_gateway.py::test_speech_placeholder`
  - `tests/test_verification.py::test_assertions`

Run from `retriva-core`:

```text
python -c "import yaml; yaml.safe_load(open('docs/governance/spec-adr-registry.yaml'))"
python -m pytest tests/test_governance_registry.py -q
```

Required result: YAML parses; the registry-integrity test passes.

Documentation-only proof: `git status` shows only the new spec pack, the
ADR file, and the registry YAML (plus the two documentation commits).

## 3. Phase B acceptance — cards and schema v2

1. `cards == derive_cards(registry)` byte-for-byte after normalization.
2. Card digests match recomputation.
3. Changing a tool name, parameter schema, or `destructive` flag without
   regenerating the card fails CI.
4. The `FAMILY` enum is exactly the sorted union of card families.
5. The schema v2 model rejects unknown fields, out-of-range/NaN confidence,
   unknown families, and inconsistent `family`/`decision` pairs.
6. No call site is wired; the full gateway baseline is unchanged.

Gate B requires all six plus owner acceptance.

## 4. Phase C acceptance — router, admission, failure

All eight safety invariants have a dedicated passing test:

1. `test_router_routed_turn_never_executes_destructive_tool`.
2. `test_deterministic_safety_outcomes_byte_identical`.
3. `test_router_failure_is_typed_fail_closed_clarify`.
4. `test_mode_off_router_disabled_is_exact_legacy`.
5. `test_capability_cards_derived_from_registry_and_digest_matched`.
6. `test_router_input_is_message_and_categorical_hints_only`.
7. `test_frozen_deterministic_recall_vocabulary_unchanged`.
8. `test_classification_path_has_no_tools_no_chat_single_call_site`.

Additional required evidence:

- One call per band turn; no second model/provider invocation on failure.
- The failure matrix returns `CLARIFY` for every category in SC5.
- A `FAMILY` route exposes only `destructive=False` tools.
- Mode `off` and flag `false` produce byte-identical legacy responses for a
  golden corpus.
- No new deterministic recall vocabulary (freeze manifest unchanged).
- Streaming behavior is unchanged and the router is not invoked.

Gate C requires all of the above plus owner acceptance.

## 5. Phase D acceptance — eval and shadow

1. Dataset v2 is additive; v1/v1.1/v1.2 remain unchanged.
2. Coverage includes all four families, EN and IT, paraphrase diversity,
   the original miss, informationally framed data questions, KB-vs-DB
   polysemy pairs, follow-up reads, out-of-catalog `CLARIFY`, and
   adversarial/injection cases.
3. `run_evaluation.py` reports:
   - zero destructive routes;
   - zero shadow-route changes for out-of-band turns;
   - plane-level precision/recall above the accepted floors;
   - clarify rate below the out-of-catalog ceiling.
4. The shadow run is on the isolated synthetic tenant; `cust_0007` is
   untouched.
5. The owner reviewed the shadow report.

**Gate D result (2026-11-06): PASSED.** The owner accepted the shadow
evidence (20/20 decision accuracy; zero destructive executions; zero
router-routed tool calls; zero shadow route changes; incident
FAMILY/CAMPAIGN at confidence 1.0) and authorized active rollout.

## 6. Phase E acceptance — active rollout

**Phase E result (2026-11-06): EXECUTED.** The runtime was moved to
`AGENT_INTENT_ROUTER_MODE=active` with `AGENT_SEMANTIC_ROUTER_ENABLED=true`
(`.env` 11:38–11:39 +01; gateway created 2026-11-06T14:29:00Z), thresholds
0.85/0.85. The delivery record is `docs/semantic-routing-delivery.md`.
Gate E owner acceptance remains pending.

1. Active mode is enabled (owner-authorized controlled environment).
2. Deployed walkthrough:
   - "How many outreach campaigns have we done?" -> "1 COMPLETED campaign
     (2026-CRA-IT)" from the campaign data path, not RAG;
   - a knowledge-base question still returns cited RAG;
   - a destructive command is terminal/refused;
   - a router failure returns a typed clarify.
3. Delivery report records flags, mode, metrics, and rollback steps.
4. The stopgap freeze is effective.
5. `cust_0007` remains untouched.

Gate E requires all of the above plus owner acceptance; the delivery
report and walkthrough are complete and awaiting that acceptance.

## 7. Rollback acceptance

Rollback is proven, not asserted:

- `AGENT_INTENT_ROUTER_MODE=off` -> exact legacy behavior.
- `AGENT_SEMANTIC_ROUTER_ENABLED=false` -> semantic router never invoked.
- Both together -> the pre-program baseline, byte-identical on the golden
  corpus.
- No migration to reverse; no data written.

## 8. Out-of-scope acceptance

The following are **not** acceptance criteria and must not be introduced:

- streaming semantic routing;
- tool-deferred routing / RAG-as-tool;
- embedding pre-routing;
- relational ingestion into the knowledge base;
- writes through the semantic layer;
- changes to `retriva-crm-assistant` or `retriva-webui`;
- production rollout on `cust_0007`.
