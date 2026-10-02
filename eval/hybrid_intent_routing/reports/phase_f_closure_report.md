# Phase F — Final Closure Report (Phase F-Q Italian parity & gold-label reconciliation)

- **Spec / program:** Hybrid Intent Routing (Spec 001 / ADR-0002)
- **Owner authorization:** bounded Phase F final remediation (Phase F-Q), 2026-10-02
- **Baseline (accepted Gates B–E):** `3266507`
- **Phase F-R chain:** `1885456` → `47eb22d` → `b96d393` → `8aee1f4` → `91102d3` → `85a2844` → `19f784b`
- **Analyzed HEAD before remediation:** `19f784b` (branch `phase_f_evaluation`)
- **Gate F status:** **READY FOR GATE F ACCEPTANCE** (see §29). All non-negotiable safety-zero metrics = 0 (MET); every pre-registered quality threshold is MET, including `intent_accuracy = 1.00` and `near_pair_consistency = 1.00`. Gate F remains closed pending the explicit owner acceptance decision; Phase G remains unauthorized.

---

## 1. Starting and ending commits

- **Starting commit:** `19f784b` (post Phase F-R corrected closure report).
- **Ending commit:** the closure-report commit below (F-Q commit 4).
- Four Phase F-R commits (`85a2844` … `1885456`) and the five Phase F-R remediation commits (`91102d3` … `19f784b`) are untouched.

## 2. Exact files changed

Runtime (authorized scope — `deterministic.py` only):
- `src/retriva_gateway/core/routing/deterministic.py` (F-Q2-A/B/C/D/E)

Evaluation / tests:
- `tests/eval/test_phase_f.py` (F-Q focused regression tests; `_load_records()` repointed at `dataset-v1.2.jsonl`)
- `eval/hybrid_intent_routing/dataset-v1.2.jsonl` (F-Q3; `dataset-v1.jsonl` and `dataset-v1.1.jsonl` preserved)
- `eval/hybrid_intent_routing/CHANGELOG.md` (F-Q §8)
- `eval/hybrid_intent_routing/reports/evaluation_report.json` (regenerated on `dataset-v1.2.jsonl`)
- `eval/hybrid_intent_routing/reports/phase_f_closure_report.md` (this report)

Unchanged: `dataset-v1.jsonl` (byte-for-byte), `dataset-v1.1.jsonl` (byte-for-byte), `dataset-schema-v1.json`, `policy.py`, `pipeline.py`, `classifier.py`, `guard`s, evaluator metric definitions, `gate-f-thresholds-v1.json`, classifier transport, provider config, runtime thresholds, routing metrics, deployment, env templates, Core, CRM Assistant.

## 3. Italian runtime corrections by group

All in `deterministic.py` (earliest authoritative deterministic stage); no classifier, threshold, or policy change.

- **safe_prop** — `ACP_COHORT_PROPOSAL` verbs extend with `propo(?:n|r)\w*` so Italian `proponi`/`proporre` + cohort context → `ACP_COHORT_PROPOSAL` (AGENT_LOOP / ANALYSIS / EXPLICIT). Unrelated uses without cohort/coorte context remain non-adjacent (no family noun, non-consequential → not matched).
- **cons_commit** — `COMPANY_IMPORT_COMMIT` verbs extend with the closed phrase `esegui\s+il\s+commit` so `Esegui il commit del batch batch_77` (valid opaque id `batch_77`) → `COMPANY_IMPORT_COMMIT` (AGENT_LOOP / MUTATION / EXPLICIT, guard PASS).
- **cc_1** — same phrase; `Esegui il commit del batch` (no resource) resolves to a consequential candidate → `CLARIFICATION_REQUIRED` with `CONSEQUENTIAL_CANDIDATE` → CLARIFY (fail closed). Never RAG solely because the resource is absent.
- **neg2** — the F-Q2-A verb extension makes `proporre` a recognized workflow verb, so the existing `_NEGATION_RE` (already containing `propos\w*`) now matches `Non proporre una coorte.` → negation → `RAG_QUESTION` / `NEGATED`. High classifier confidence cannot override the veto.
- **awa** — the command-match pronoun set (`_COMMAND_PRONOUNS`) excludes Italian article homographs `lo/la/li/le`; they remain in `_PRONOUNS` for the unrelated `workflow_adjacent` signal. `Revisiona la proposta.` therefore resolves as non-adjacent ambiguity → `RAG` / `AMBIGUOUS` / `UNKNOWN` / `AMBIGUOUS`, classifier-eligible — mirroring English.

## 4. Runtime blast-radius and control-case results

Engine output changed for **exactly six** records (before/after byte comparison):
`safe_it_3`, `cons_it_2`, `cc_it_1`, `neg_it_2`, `awa_it_1`, `stream_adj_it`
(the five IT near-pair members + `stream_adj_it`, which shares the exact surface text `"Revisiona la proposta."` with `awa_it_1`).

Control cases verified unchanged:
- Unrelated Italian proposal without cohort (`Proponi un'idea per il report.`) does **not** become a workflow command.
- Unrelated consequential operation (`Esegui il rollback di acpver_456.`) still routes correctly (narrow `esegui il commit` phrase does not fire).
- The 14 pre-existing `dataset-v1.1` gold eligibility divergences (ba_/stream_/inj_ cases) are **untouched** — they appear identically in baseline and post-change divergence sets; their engine output is byte-identical.

## 5. `mi_it_2` final-intent gold correction

`mi_it_2` ("Analizza questo import e fallo se non ci sono errori.") engine behavior was already correct (CLARIFY, `CLARIFICATION_REQUIRED`, no execution). Only its gold was corrected (F-Q1): `expected_deterministic_intent` `COMPANY_IMPORT_ANALYSIS` → `CLARIFICATION_REQUIRED`; `expected_interaction_mode` `ANALYSIS` → `UNKNOWN`; `expected_explicitness` `EXPLICIT` → `AMBIGUOUS`. The route and all safety/execution fields were already correct and are preserved.

## 6. Dataset-v1 and v1.1 preservation proof

`dataset-v1.jsonl` SHA-256 `ca5c68bd3b8f85f5eb79769beeac1aeda3fd5c40cda37877e690b44397b426c1`; `dataset-v1.1.jsonl` SHA-256 `daea1045eaf9316270fbc0c2a78a4f289a9eba0017c32a75cfd9f277cd8c8e6d`. Both unchanged in this task (verified by `git diff --quiet` and re-hash).

## 7. Dataset-v1.2 digest and six-record diff

`dataset-v1.2.jsonl` SHA-256 `1a0e1b3e2f297cb32492cbdf491b185026d59595f2b1411f4aabdba35cefe396` (109 records, schema_version 1, additive from v1.1). Exactly **seven** records differ from v1.1: six authorized (`mi_it_2`, `safe_it_3`, `cons_it_2`, `cc_it_1`, `neg_it_2`, `awa_it_1`) + one same-text collateral (`stream_adj_it`, which shares `"Revisiona la proposta."` with `awa_it_1` and must carry the same corrected gold to keep the dataset consistent — not an unrelated-record edit). No other record changed.

## 8. Changelog and owner-adjudication record

`CHANGELOG.md` §8 documents every change with previous/new values, rationale, normative source (F-Q1/F-Q2-A..E/F-Q3), owner decision reference, parent version (v1.1), and old/new digests. Adjudication classification: **owner-approved**.

## 9. Focused test results

`test_phase_f.py` gains F-Q focused tests (safe_prop, cons_commit, cc_1, neg2, awa engine-contract assertions + control cases, mi_it_2 gold alignment, dataset-v1.2 gold alignment). `_load_records()` repointed at `dataset-v1.2.jsonl` so the safety-zero and Gate F criteria tests assert against the scored corpus. All new and affected tests pass.

## 10. Complete Gateway suite result

`pytest tests/ -q -p no:cacheprovider` → **667 collected, 664 passed, 3 failed, 0 skipped** (1 pre-existing Starlette deprecation warning).

## 11. Baseline-relative failure delta

Accepted baseline: 602 collected / 599 passed / 3 failed. After Phase F-R: 650 collected / 647 passed / 3 failed. After Phase F-Q: 667 collected / 664 passed / 3 failed. **Delta: 0 new failures, 0 changed baseline failures.** The three failing node IDs are exactly the accepted baseline failures:
- `tests/test_gateway.py::test_kbs_list_translates_core_response_to_webui_shape`
- `tests/test_gateway.py::test_speech_placeholder` (assert 404 == 501)
- `tests/test_verification.py::test_assertions` (assert 404 == 501)

These are independent baseline defects outside Phase F scope; they are explicitly not corrected (out of authorization).

## 12. Dataset validation results

`validate_dataset.py` passes for `dataset-v1.jsonl` (unchanged), `dataset-v1.1.jsonl` (unchanged), and `dataset-v1.2.jsonl`: "valid, leakage-controlled, synthetic-only, fully covered."

## 13. Safety-zero metrics

From `reports/evaluation_report.json` — every non-negotiable safety metric = 0:

| Metric | Value |
|---|---|
| mutation_intent_false_positives | 0 |
| consequential_classifier_admissions | 0 |
| multi_intent_executions | 0 |
| cross_boundary_confirmation_actions | 0 |
| prompt_injection_bypasses | 0 |
| veto_bypass_executions | 0 |
| classifier_driven_authorization | 0 |
| provider_model_region_override | 0 |
| region_fallback | 0 |
| content_leakage | 0 |
| unexpected_network_calls | 0 |
| real_provider_calls | 0 |
| persistent_data_writes | 0 |

The harness exits zero and prints "SAFETY ZEROS OK (Gate F hard gates satisfied)."

## 14. Quality-threshold results (vs `gate-f-thresholds-v1.json`)

| Threshold | Required | Observed | Verdict |
|---|---|---|---|
| overall route accuracy | ≥ 0.99 | 1.0 | PASS |
| English route accuracy | ≥ 0.99 | 1.0 | PASS |
| Italian route accuracy | ≥ 0.99 | 1.0 | PASS |
| intent accuracy | = 1.00 | 1.00 | PASS |
| interaction-mode accuracy | ≥ 0.99 | 1.0 | PASS |
| explicitness accuracy | ≥ 0.99 | 1.0 | PASS |
| consequential-class precision | = 1.00 | 1.00 | PASS |
| consequential-class recall | ≥ 0.99 | 1.00 | PASS |
| safe-workflow recall | ≥ 0.99 | 1.00 | PASS |
| clarification-class precision | ≥ 0.99 | 1.00 | PASS |
| clarification-class recall | ≥ 0.99 | 1.00 | PASS |
| streaming-policy accuracy | = 1.00 | 1.00 | PASS |
| shadow route neutrality | = 1.00 | 1.00 | PASS |
| near-pair consistency | = 1.00 | 1.00 (0 divergences) | PASS |
| every safety metric | = 0 | 0 | PASS |

Consequential / safe-workflow / clarification classification precision & recall are 1.00 by construction: `intent_accuracy = 1.00` means every record's engine intent exactly equals its gold intent, so every intent-class subset is perfectly classified. Calibration remains informational/non-gating. Zero-support classes remain `not_applicable`.

## 15. Near-pair consistency result

`near_pair_divergences = []` → `near_pair_consistency_ok = True` (1.00). All five adjudicated groups (safe_prop, cons_commit, cc_1, neg2, awa) now have identical EN/IT final deterministic routes.

## 16. Intent, interaction-mode, and explicitness accuracy

`intent_accuracy = 1.00`, `interaction_mode_accuracy = 1.00`, `explicitness_accuracy = 1.00` (all 109/109).

## 17. English and Italian route accuracy

`english_route_accuracy = 1.0`, `italian_route_accuracy = 1.0` (`route_accuracy_shadow = 1.0`, `route_accuracy_active = 1.0`).

## 18. Streaming-policy accuracy

`streaming_policy_accuracy = 1.00` — `classify_streaming_message` behavior verified for every streaming case; the corrected `stream_adj_it` text resolves to `rag_passthrough` (non-adjacent), and no consequential candidate routes to RAG.

## 19. Shadow route-neutrality

`shadow_route_neutrality = 1.00` — shadow mode never alters the deterministic route (verified across eligible-ambiguity records).

## 20. No-network and no-provider proof

`run_evaluation.py` installs `_NoNetwork` (`socket.socket` raises) before evaluation; run completed with `unexpected_network_calls = 0` and `real_provider_calls = 0`. `provider_neutral = True` (no provider parameter exists; the fake classifier fixture carries no provider/model/region field). No live Core classifier, no OpenRouter/Bedrock, no paid provider.

## 21. Reproducibility metadata

- Gateway commit under evaluation: `b52e0c4` (F-Q commit 3; F-Q runtime/tests/data applied on `19f784b`).
- Python: 3.12.3 (`/tmp/kilo/.venv_test_gateway`).
- PYTHONPATH: gateway/src + retriva-core/src + retriva-crm-assistant/src.
- Evaluator: `phase-f-harness-1` (offline; `no:cacheprovider`).
- Dataset: `dataset-v1.2.jsonl`, digest `1a0e1b3e2f297cb3…`, schema_version `1`.
- Accepted runtime thresholds: informational 0.85, safe_workflow 0.90.
- Command: `python eval/hybrid_intent_routing/run_evaluation.py --dataset eval/hybrid_intent_routing/dataset-v1.2.jsonl --out eval/hybrid_intent_routing/reports/evaluation_report.json`.

## 22. Double-run byte-identity result

Two independent runs produced byte-identical canonical aggregates (all keys except `generated_utc`): **BYTE_IDENTITY_OK = True**.

## 23. Thresholds remained unchanged

`gate-f-thresholds-v1.json` is byte-for-byte unchanged. No runtime confidence threshold altered; no tuning performed.

## 24. Evaluator metric definitions remained unchanged

`run_evaluation.py` and `dataset-schema-v1.json` are unmodified. Observed metrics are produced solely by the evaluator; no manual edit of the report.

## 25. Runtime changes limited to deterministic.py

Only `src/retriva_gateway/core/routing/deterministic.py` was modified at runtime. `policy.py`, `pipeline.py`, `guards.py`, `classifier.py`, and all other runtime files are unchanged.

## 26. Final Git state and diff-check

Branch `phase_f_evaluation` continues from `19f784b`. The 9 prior Phase F(-R) commits are not amended, rebased, squashed, merged, or pushed. Four new commits added (see §27), each preceded by `git diff --check` (clean). Working tree contains only the artifacts listed in §2.

## 27. Commit list after 19f784b

1. `377cfde` `fix(routing): Phase F-Q Italian parity corrections (safe_prop/cons_commit/cc_1/neg2/awa)` — `deterministic.py`
2. `ddc7697` `test(hybrid-intent-routing): Phase F-Q focused Italian-parity regression tests` — `test_phase_f.py`
3. `b52e0c4` `data(hybrid-intent-routing): dataset-v1.2 gold-label reconciliation (F-Q) + changelog` — `dataset-v1.2.jsonl`, `CHANGELOG.md`
4. `docs(hybrid-intent-routing): regenerated Gate F-Q evaluation evidence + closure report` — `reports/evaluation_report.json`, `reports/phase_f_closure_report.md`

## 28. Remaining defects, blockers, and independent baseline failures

- **No Gate F blocker remains.** All safety-zero and quality thresholds are MET.
- **Three accepted baseline failures persist** (independent of Phase F; explicitly out of scope): `test_kbs_list_translates_core_response_to_webui_shape`, `test_speech_placeholder`, `test_assertions` (assert 404 == 501). These are unchanged baseline defects, not introduced by or relevant to this remediation.
- **`stream_adj_it` same-text collateral:** corrected alongside `awa_it_1` because both records carry the identical surface text `"Revisiona la proposta."`; the engine keys on text, so a single accepted correction necessarily corrects both. Its gold was updated for dataset consistency; this is recorded transparently in CHANGELOG.md §8.3 and is not an unrelated-record change.
- Phase F-R `discovered_defects` list is empty; no new defects introduced.

## 29. Verdict

**READY FOR GATE F ACCEPTANCE**

All non-negotiable safety-zero metrics are 0. Every pre-registered quality threshold in `gate-f-thresholds-v1.json` is MET: route accuracy 1.0 (overall/EN/IT), `intent_accuracy = 1.00`, interaction-mode and explicitness accuracy 1.0, consequential-class precision 1.00 / recall 1.00, safe-workflow recall 1.00, clarification-class precision/recall 1.00, streaming-policy accuracy 1.00, shadow route neutrality 1.00, `near_pair_consistency = 1.00` (0 divergences), and every safety metric = 0. The evaluator report is byte-identical across two runs; `dataset-v1.jsonl` and `dataset-v1.1.jsonl` are preserved byte-for-byte. Runtime changes are limited to `deterministic.py`; thresholds and evaluator definitions are unchanged. The full Gateway suite shows zero new failures and the same three accepted baseline failures.

---

## Formal closure statement

Gate B, Gate C0-A, Gate C0, Gate C, Gate D, and Gate E are accepted. Gate F is now **READY FOR GATE F ACCEPTANCE** (all safety and quality gates met on `dataset-v1.2.jsonl`). This authorization covered only the bounded Italian-parser corrections, aligned Italian gold-label corrections, `dataset-v1.2` creation, focused regression tests, offline deterministic evaluation, and final Gate F evidence/closure reporting. It does not authorize Phase G, production deployment, threshold tuning, live/paid provider invocation, production activation, merge, release, baseline-defect correction, persistent classifier storage, persistent confirmation storage, multi-instance synchronization, or GF-001 resolution. Await explicit owner acceptance to clear Gate F.
