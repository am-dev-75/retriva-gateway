# Phase F-R Remediation Changelog — Hybrid Intent Routing (Spec 001 / ADR-0002)

Owner authorization: bounded Phase F safety remediation (Phase F-R), 2026-10-02.
Branch `phase_f_evaluation`, baseline Gate E tip `3266507`. Gate F remains
closed; Phase G remains unauthorized.

## 1. Scope

Authorized corrections (F-R1..F-R7):

1. PHASEF-DEFECT-1 — policy clarification typing (runtime).
2. Italian hypothetical-anchor gap (runtime).
3. Straight single-quote masking (runtime).
4. Metalinguistic quotation-framing rule (runtime + normative doc).
5. Contextual Italian clitic multi-intent (runtime).
6. Focused regression tests.
7. Versioned gold-label corrections for 5 conclusively invalid labels (dataset).
8. Metric-artifact reconciliation.
9. Pre-registered quality thresholds.
10. Re-evaluation against corrected dataset.
11. Corrected closure report.

Explicitly out of scope: Phase G, production rollout, live/paid providers,
threshold tuning, runtime threshold changes, broad IT parser redesign, the seven
PHASEF-DEFECT-4 near-pair groups (deferred, F-R5), baseline-defect correction,
GF-001, persistent storage, multi-instance sync.

## 2. Runtime corrections (files: `src/.../routing/deterministic.py`, `policy.py`)

- **F-R1**: `policy._clarification` now passes a `DeterministicResult` (not a
  bare list) to `build_clarification` when `routed.clarification is None`.
- **F-R2a**: `_HYPOTHETICAL_ANCHORS` extended with `suppon\w+`, `ipotizz\w+`,
  `immagin\w+`, `se\s+fossimo` (covers `supponiamo`, `ipotizziamo`, `immaginiamo`,
  `se fossimo`; `se potessimo` already covered by `se\s+potess\w+`).
- **F-R2b**: `_QUOTED_PATTERNS` adds a straight single-quote span pattern
  `'[^'\n]{1,400}'`, bounded so ordinary apostrophes/contractions (single quote,
  no closing pair) are not masked.
- **F-R2c**: new closed `_QUOTE_FRAMING_ANCHORS` and rule `R-QUOTE-FRAMING`
  (priority 32) for metalinguistic command-quoting (`quote/cite/repeat/
  transcribe/write down this command`; IT `cita/citando questo comando`,
  `ripeti/trascrivi/scrivi questo comando`). Maps to the accepted R-QUOTED
  framing veto; no new TR. Does not fire on every colon and does not disable
  genuine direct commands.
- **F-R3**: `_add_clitic_multi_intent` recognizes `fallo/falla/falli/falle`
  (incl. `fallo pure`) as a second-operation signal only when a sibling clause
  establishes a workflow operation/family. Enables Policy B clarification
  without registering the clitic as a global operation verb; a standalone bare
  affirmative (`Fallo.`) stays on the Phase C path.

## 3. Dataset gold-label corrections (F-R4)

`dataset-v1.jsonl` is preserved byte-for-byte (digest
`ca5c68bd3b8f85f5…`). `dataset-v1.1.jsonl` carries the five corrections.
Revised digest `daea1045eaf93162…`.

Each corrected label previously asserted execution (`expected_route_active =
AGENT_LOOP`, `expected_tool_execution = true`, `expected_bypass_reason =
guard_terminal`) for a framing-veto case — contradicting architecture §2
framing vetoes and owner F-D4. Corrected to informational/RAG, no execution.

| Change ID | Case | Before (route / intent / explicitness) | After (route / intent / explicitness) |
|---|---|---|---|
| PHASEF-GOLD-hyp_it_1 | hyp_it_1 | AGENT_LOOP / ACP_ROLLBACK / EXPLICIT | RAG / RAG_QUESTION / HYPOTHETICAL |
| PHASEF-GOLD-quo_en_1 | quo_en_1 | AGENT_LOOP / ACP_ACTIVATION / EXPLICIT | RAG / RAG_QUESTION / QUOTED_EXAMPLE |
| PHASEF-GOLD-quo_it_1 | quo_it_1 | AGENT_LOOP / ACP_ACTIVATION / EXPLICIT | RAG / RAG_QUESTION / QUOTED_EXAMPLE |
| PHASEF-GOLD-quo_en_2 | quo_en_2 | AGENT_LOOP / ACP_ACTIVATION / EXPLICIT | RAG / RAG_QUESTION / QUOTED_EXAMPLE |
| PHASEF-GOLD-quo_it_2 | quo_it_2 | AGENT_LOOP / ACP_ACTIVATION / EXPLICIT | RAG / RAG_QUESTION / QUOTED_EXAMPLE |

Accepted normative source: architecture.md §2 R-HYPOTHETIC/R-QUOTED framing
vetoes; acceptance.md Gate F safety-first; owner F-D4. Adjudication:
owner-approved (F-R4), synthetic reviewer identifiers `synthetic-reviewer-1` /
`synthetic-reviewer-2`. Rationale codes unchanged (`D2_HYPOTHETICAL`,
`R_QUOTED`). Prior labels preserved in §3.1.

### 3.1 Prior gold labels (preserved, not active)

```
hyp_it_1:  route=AGENT_LOOP intent=ACP_ROLLBACK mode=DESTRUCTIVE_MUTATION
           explicitness=EXPLICIT agent_loop=true tool_exec=true guard=pass
           bypass_reason=guard_terminal
quo_en_1/it_1/en_2/it_2: route=AGENT_LOOP intent=ACP_ACTIVATION mode=MUTATION
           explicitness=EXPLICIT agent_loop=true tool_exec=true guard=pass
           bypass_reason=guard_terminal
```

`mi_it_2` was **not** changed (owner F-R4): its expected route (CLARIFY) is
correct; only its `expected_deterministic_intent` field remains
`COMPANY_IMPORT_ANALYSIS` while the clarifying route emits
`CLARIFICATION_REQUIRED` — see §5.

## 4. Metric-artifact reconciliation (F-R6)

- **Generated artifact**: `reports/evaluation_report.json` (produced by
  `run_evaluation.py`; canonical observed metrics; byte-identical across two
  runs apart from `generated_utc`).
- **Pre-registered thresholds**: `gate-f-thresholds-v1.json` (owner F-R7) —
  thresholds only, no observed values.
- **Manually maintained draft** (renamed): `phase_f_metrics_draft.json`
  (formerly `expected-metrics.json`, commit `8aee1f4`). It asserted observed
  quality metrics (`route_accuracy_shadow 0.9908`, `intent_accuracy 1.0`,
  `italian_route_accuracy 0.9811`) that **disagreed** with the manually
  maintained closure report (commit `85a2844`, which stated 0.94/0.95/0.93).
  Neither artifact was generated by the evaluator. The disagreement is recorded
  here and not concealed; canonical observed metrics now live only in the
  generated report. The draft is retained for defect/owner-decision provenance
  only and is explicitly NOT a source of expected results.

## 5. Known residual (outside authorized correction set)

`mi_it_2` (`Analizza questo import e fallo se non ci sono errori.`) routes to
CLARIFY with deterministic intent `CLARIFICATION_REQUIRED`. Its gold
`expected_deterministic_intent` remains `COMPANY_IMPORT_ANALYSIS` (owner F-R4
held it unchanged). The route — the safety-relevant field — is correct. The
single intent-accuracy delta (1/109 = 0.9908) and the safe-workflow recall
delta stem solely from this gold-intent/route inconsistency, not from a runtime
defect. Disposition requires owner decision (correct the gold intent field, or
accept the route-gated interpretation).

## 6. Deferred PHASEF-DEFECT-4 near-pair groups (F-R5)

The authorized fixes incidentally repaired the `hyp` and `mi_2` near-pairs.
Five groups remain divergent (EN vs IT route differs). For every group, both
languages' actual routes match their respective gold labels; the divergence is
that the two languages route differently — an EN/IT parity gap driven by IT
operation/negation/commit detection and gold labels that encode the divergent
expectation. No code or label change was made for these groups (F-R5).

| Group | EN case / text | EN route | IT case / text | IT route | Code / label / both defective | Recommended future disposition |
|---|---|---|---|---|---|---|
| safe_prop | safe_en_3 "Propose a new cohort." | AGENT_LOOP | safe_it_3 "Proponi una nuova coorte." | CLARIFY | both (IT proposal detection + IT gold) | authorize IT safe-workflow detection + align gold |
| cons_commit | cons_en_2 "Commit batch batch_77." | AGENT_LOOP | cons_it_2 "Esegui il commit del batch batch_77." | RAG | both (IT "esegui il commit del" not matched + IT gold) | authorize IT commit detection + align gold |
| cc_1 | cc_en_1 "Commit the batch." | CLARIFY | cc_it_1 "Esegui il commit del batch." | RAG | both (IT detection + IT gold) | authorize IT commit detection + align gold |
| neg2 | neg_en_2 "Do not propose a cohort." | RAG | neg_it_2 "Non proporre una coorte." | CLARIFY | both (IT negation detection + IT gold) | authorize IT negation detection + align gold |
| awa | awa_en_1 "Review the proposal." | RAG | awa_it_1 "Revisiona la proposta." | CLARIFY | both (IT ambiguous-adjacent detection + IT gold) | authorize IT adjacency detection + align gold |

Because the accepted Gate F near-pair threshold (1.00) cannot be reached without
changing these deferred groups, **Gate F remains blocked** (F-R5).

## 7. Files changed in Phase F-R (commits listed in closure report)

- `src/retriva_gateway/core/routing/deterministic.py` (F-R1..F-R3)
- `src/retriva_gateway/core/routing/policy.py` (F-R1)
- `eval/hybrid_intent_routing/dataset-v1.1.jsonl` (F-R4)
- `eval/hybrid_intent_routing/gate-f-thresholds-v1.json` (F-R7)
- `eval/hybrid_intent_routing/methodology.md`, `README.md` (F-R2c, F-R6)
- `eval/hybrid_intent_routing/phase_f_metrics_draft.json` (rename, F-R6)
- `eval/hybrid_intent_routing/CHANGELOG.md` (this file)
- `tests/eval/test_phase_f.py`, `tests/test_routing_policy.py` (regression)
- `eval/hybrid_intent_routing/reports/evaluation_report.json`,
  `reports/phase_f_closure_report.md` (evidence)

## 8. Phase F-Q — Italian parity & final gold-label reconciliation

Owner authorization: bounded Phase F final remediation (Phase F-Q), 2026-10-02.
Branch `phase_f_evaluation`. Carried forward from Gate E tip `3266507` → Phase
F-R chain → `19f784b`. Gate F remains **closed**; Phase G remains unauthorized.

### 8.1 Scope

Authorized corrections (F-Q1..F-Q5):

1. One dataset-only gold-label correction for `mi_it_2` (F-Q1).
2. Narrow Italian parser corrections in `deterministic.py` for five adjudicated
   near-pair groups: `safe_prop`, `cons_commit`, `cc_1`, `neg2`, `awa` (F-Q2).
3. Aligned Italian gold-label corrections for `safe_it_3`, `cons_it_2`,
   `cc_it_1`, `neg_it_2`, `awa_it_1` (F-Q3).
4. `dataset-v1.2.jsonl` created, derived from `dataset-v1.1.jsonl` (F-Q3).
5. Focused regression tests added (F-Q).
6. Offline deterministic evaluation re-run; final Gate F evidence + closure report.

`dataset-v1.jsonl` and `dataset-v1.1.jsonl` are preserved **byte-for-byte**
(digests unchanged). `dataset-v1.2.jsonl` is additive, schema_version 1.

### 8.2 Runtime corrections (file: `src/.../routing/deterministic.py` only)

- **F-Q2-A (safe_prop)**: `ACP_COHORT_PROPOSAL` verbs extended with
  `propo(?:n|r)\w*` so Italian "proponi"/"proporre" (cohort context) route to
  `ACP_COHORT_PROPOSAL` (AGENT_LOOP / ANALYSIS / EXPLICIT). Unrelated uses
  without cohort/coorte context remain non-adjacent (no family noun, non-
  consequential → not matched).
- **F-Q2-B (cons_commit)**: `COMPANY_IMPORT_COMMIT` verbs extended with the
  closed phrase `esegui\s+il\s+commit` so "Esegui il commit del batch
  batch_77" (valid opaque id batch_77) routes to `COMPANY_IMPORT_COMMIT`
  (AGENT_LOOP / MUTATION / EXPLICIT, guard PASS). "Esegui il commit del batch"
  (no resource) is a consequential candidate → CLARIFY (guard fail-closed). The
  phrase is narrow: it does not fire on "esegui il rollback" or unrelated
  "commit".
- **F-Q2-C (cc_1)**: covered by the F-Q2-B phrase; no-resource form resolves to
  `CLARIFICATION_REQUIRED` with reason `CONSEQUENTIAL_CANDIDATE` → CLARIFY
  (fail closed), never RAG solely because the resource is absent.
- **F-Q2-D (neg2)**: the F-Q2-A verb extension makes "proporre" a recognized
  workflow verb, so the existing `_NEGATION_RE` (which already includes
  `propos\w*`) now matches "Non proporre una coorte." → negation → RAG /
  RAG_QUESTION / NEGATED. High classifier confidence cannot override the veto.
- **F-Q2-E (awa)**: `workflow_adjacent`'s command-match path no longer treats
  Italian articles "lo/la/li/le" as object pronouns (new `_COMMAND_PRONOUNS`
  excludes them; they remain in `_PRONOUNS` for the unrelated workflow-adjacency
  signal). "Revisiona la proposta." therefore resolves as non-adjacent
  ambiguity → RAG / AMBIGUOUS / UNKNOWN / AMBIGUOUS, classifier-eligible — the
  accepted English-mirroring behavior.

### 8.3 Dataset gold-label corrections (F-Q3, parent = dataset-v1.1)

`dataset-v1.jsonl` digest `ca5c68bd3b8f85f5eb79769beeac1aeda3fd5c40cda37877e690b44397b426c1`
(unchanged). `dataset-v1.1.jsonl` digest
`daea1045eaf9316270fbc0c2a78a4f289a9eba0017c32a75cfd9f277cd8c8e6d` (unchanged).
`dataset-v1.2.jsonl` digest
`1a0e1b3e2f297cb32492cbdf491b185026d59595f2b1411f4aabdba35cefe396` (new).
Exactly seven records differ from v1.1 (six authorized + one same-text
collateral, see §8.4).

| Change ID | Case | Before (route / intent / explicitness) | After (route / intent / explicitness) |
|---|---|---|---|
| PHASEFQ-GOLD-mi_it_2 | mi_it_2 | CLARIFY / COMPANY_IMPORT_ANALYSIS / EXPLICIT | CLARIFY / CLARIFICATION_REQUIRED / AMBIGUOUS |
| PHASEFQ-GOLD-safe_it_3 | safe_it_3 | CLARIFY / CLARIFICATION_REQUIRED / AMBIGUOUS | AGENT_LOOP / ACP_COHORT_PROPOSAL / ANALYSIS / EXPLICIT |
| PHASEFQ-GOLD-cons_it_2 | cons_it_2 | RAG / AMBIGUOUS / AMBIGUOUS | AGENT_LOOP / COMPANY_IMPORT_COMMIT / MUTATION / EXPLICIT (guard pass) |
| PHASEFQ-GOLD-cc_it_1 | cc_it_1 | RAG / AMBIGUOUS / AMBIGUOUS | CLARIFY / CLARIFICATION_REQUIRED / EXPLICIT (guard fail_closed) |
| PHASEFQ-GOLD-neg_it_2 | neg_it_2 | CLARIFY / CLARIFICATION_REQUIRED / AMBIGUOUS | RAG / RAG_QUESTION / NEGATED |
| PHASEFQ-GOLD-awa_it_1 | awa_it_1 | CLARIFY / CLARIFICATION_REQUIRED / AMBIGUOUS | RAG / AMBIGUOUS / AMBIGUOUS (eligible) |
| PHASEFQ-GOLD-stream_adj_it | stream_adj_it | CLARIFY / CLARIFICATION_REQUIRED / AMBIGUOUS | RAG / AMBIGUOUS / AMBIGUOUS (eligible; streaming rag_passthrough) |

`stream_adj_it` shares the exact surface text "Revisiona la proposta." with
`awa_it_1`; correcting `awa_it_1` deterministically corrects `stream_adj_it` (the
engine keys on text). Its gold is updated to remain dataset-consistent (the same
text may not carry two incompatible gold labels). This is a same-text collateral,
not an unrelated-record edit: no other record's gold was altered.

Per-record detail (required fields):

- **mi_it_2** — prev: `expected_deterministic_intent=COMPANY_IMPORT_ANALYSIS`,
  `expected_interaction_mode=ANALYSIS`, `expected_explicitness=EXPLICIT`.
  new: `CLARIFICATION_REQUIRED`, `UNKNOWN`, `AMBIGUOUS`. reason: final routing
  intent is CLARIFICATION_REQUIRED under Multi-intent Policy B (terminal); the
  detected operation COMPANY_IMPORT_ANALYSIS is intermediate. normative: F-Q1;
  parent v1.1; old digest `daea1045…`; new `1a0e1b3e…`.
- **safe_it_3** — prev: CLARIFY / CLARIFICATION_REQUIRED / UNKNOWN / AMBIGUOUS.
  new: AGENT_LOOP / ACP_COHORT_PROPOSAL / ANALYSIS / EXPLICIT, agent_loop=true,
  tool_exec=true, guard=not_applicable, bypass=deterministic_terminal.
  normative: F-Q2-A; parent v1.1; old `daea1045…`; new `1a0e1b3e…`.
- **cons_it_2** — prev: RAG / AMBIGUOUS / UNKNOWN / AMBIGUOUS, guard=
  not_applicable. new: AGENT_LOOP / COMPANY_IMPORT_COMMIT / MUTATION / EXPLICIT,
  guard=pass, bypass=guard_terminal, agent_loop=true, tool_exec=true.
  normative: F-Q2-B; parent v1.1; old `daea1045…`; new `1a0e1b3e…`.
- **cc_it_1** — prev: RAG / AMBIGUOUS / UNKNOWN / AMBIGUOUS, guard=
  not_applicable. new: CLARIFY / CLARIFICATION_REQUIRED / UNKNOWN / EXPLICIT,
  guard=fail_closed, bypass=consequential_candidate, agent_loop=false,
  tool_exec=false. normative: F-Q2-C; parent v1.1; old `daea1045…`; new
  `1a0e1b3e…`.
- **neg_it_2** — prev: CLARIFY / CLARIFICATION_REQUIRED / UNKNOWN / AMBIGUOUS.
  new: RAG / RAG_QUESTION / UNKNOWN / NEGATED, agent_loop=false, tool_exec=false.
  normative: F-Q2-D; parent v1.1; old `daea1045…`; new `1a0e1b3e…`.
- **awa_it_1** — prev: CLARIFY / CLARIFICATION_REQUIRED / UNKNOWN / AMBIGUOUS.
  new: RAG / AMBIGUOUS / UNKNOWN / AMBIGUOUS (eligibility true, call 1,
  recommendation ACP_REVIEW, confidence 0.92, route_active AGENT_LOOP unchanged).
  normative: F-Q2-E; parent v1.1; old `daea1045…`; new `1a0e1b3e…`.
- **stream_adj_it** — prev: CLARIFY / CLARIFICATION_REQUIRED / UNKNOWN /
  AMBIGUOUS, eligibility false, call 0, recommendation None, streaming
  stream_clarify. new: RAG / AMBIGUOUS / UNKNOWN / AMBIGUOUS, eligibility true,
  call 1, recommendation ACP_REVIEW, confidence 0.92, streaming rag_passthrough
  (same-text collateral of awa_it_1). normative: F-Q2-E + dataset consistency;
  parent v1.1; old `daea1045…`; new `1a0e1b3e…`.

### 8.4 Verification

- `validate_dataset.py` PASSES on v1, v1.1, and v1.2 (schema v1, synthetic-only,
  leakage-controlled, fully covered).
- v1 and v1.1 digests unchanged.
- Exactly seven records differ between v1.1 and v1.2 (the six authorized + one
  same-text collateral). No other record changed.
- Engine output changed for exactly six records (the five IT near-pair members +
  `stream_adj_it`); all 14 pre-existing eligibility divergences in v1.1 gold are
  untouched (blast radius verified by before/after byte comparison).
- `run_evaluation.py` on `dataset-v1.2.jsonl`: route_accuracy_shadow=1.0,
  route_accuracy_active=1.0, intent_accuracy=1.0, interaction_mode_accuracy=1.0,
  explicitness_accuracy=1.0, english_route_accuracy=1.0, italian_route_accuracy=
  1.0, near_pair_divergences=[] (`near_pair_consistency_ok=True`),
  all `safety_zeros`=0, provider_neutral=True, content_leakage_free=True.
  Report is byte-identical across two runs (excluding `generated_utc`).
- Full Gateway suite: 664 passed, 3 accepted baseline failures
  (test_kbs_list_translates_core_response_to_webui_shape, test_speech_placeholder,
  test_assertions); zero new failures; the same three accepted failing node IDs.
