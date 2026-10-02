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
