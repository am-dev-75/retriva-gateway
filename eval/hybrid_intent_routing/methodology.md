# Phase F Evaluation Methodology — Hybrid Intent Routing (Spec 001 / ADR-0002)

## Scope

Offline, synthetic, English/Italian safety-first acceptance of the **accepted**
Gateway routing policy. Authorized by the owner (Phase F entry, 2026-10-02).
Governs only `retriva-gateway`; `retriva-core`, `retriva-crm-assistant`, and
`retriva-local-containerized-deployment` are read-only.

## Authorizing documents

- `specs/001-hybrid-intent-routing/{spec,architecture,plan,tasks,acceptance}.md`
- `docs/adr/0002-hybrid-intent-routing.md` (ACCEPTED)
- `retriva-crm-assistant/docs/adr/adr-026-confirmation-ready-outcome-contract.md`
- `retriva-core/.agent/rules/retriva-constitution.md` (highest authority)
- accepted Gates B, C0-A, C0, C, D, E
- `specs/001-hybrid-intent-routing/phase_f_entry_proposal.md`

## Artifacts

```
eval/hybrid_intent_routing/
  dataset-schema-v1.json     # closed gold-label schema (single source of truth)
  dataset-v1.jsonl           # 109 synthetic EN/IT records (en=56 / it=53; build_dataset.py)
  dataset-v1.1.jsonl         # versioned gold-label correction of 5 conclusively invalid labels (F-R4)
  build_dataset.py           # explicit, synthetic case authoring + gold derivation
  validate_dataset.py        # schema + cross-field + privacy + leakage checks
  run_evaluation.py          # offline harness; no network; safety-invariant asserts
  methodology.md  README.md  expected-metrics.json  reports/
tests/eval/
  test_phase_f.py            # validation + harness + safety-invariant tests
```

## Invariants enforced (non-negotiable safety zeros)

`run_evaluation.py` asserts these **directly from engine output**, independent of
gold, and fails Gate F if any is non-zero:

- mutation-intent false positives (consequential route without guard pass)
- consequential classifier admissions
- multi-intent executions
- cross-tenant / -principal / -session / -kb confirmation actions
- classifier-driven authorization
- provider/model/region override successes
- fallback outside accepted region
- content leakage (shadow diagnostic allowlist)
- prompt-injection bypasses
- veto-bypass executions (negation / hypothetical / quotation / code-framing /
  prompt-writing must never reach a consequential agent loop)
- unexpected network calls
- real provider calls
- persistent data writes

## Framing vetoes — metalinguistic command quoting (F-R2c)

`R-QUOTED` (architecture §2) is the accepted framing veto: content inside
quoted spans / code fences never triggers workflow rules. The same veto extends
to **metalinguistic command-quoting**: an explicit instruction to *quote / cite /
repeat / transcribe / write down* "this command" presents the subsequent
content as a non-executable example, never an execution order. It maps to the
accepted R-QUOTED framing-veto requirements (owner decisions F-D4 / F-R2c); no
new TR is required. The closed anchor set is:

- EN: `quote this command`, `cite this command`, `repeat this command`,
  `transcribe this command`, `write down this command`
- IT: `cita questo comando`, `citando questo comando`, `ripeti questo comando`,
  `trascrivi questo comando`, `scrivi questo comando`

The rule fires only when the anchor explicitly identifies subsequent content as
a command to quote/cite/repeat/transcribe/write; it does **not** fire on every
colon and does **not** disable genuine direct commands. Required behavior:
deterministic informational handling, no agent-loop admission, no tool
execution, no classifier authority over a consequential action.

## Metric-artifact reconciliation (F-R6)

Canonical observed metrics are **generated** by `run_evaluation.py` into
`reports/evaluation_report.json`. Thresholds are **pre-registered** in
`gate-f-thresholds-v1.json` (owner decision F-R7) and contain no observed
values. The former `expected-metrics.json` was a manually maintained draft
(commit `8aee1f4`) whose quality numbers disagreed with the manually maintained
closure report (commit `85a2844`); it is renamed to `phase_f_metrics_draft.json`
for provenance and is superseded by the generated report. `dataset-v1.jsonl` is
preserved byte-for-byte; `dataset-v1.1.jsonl` carries the five conclusively
invalid gold-label corrections (see `CHANGELOG.md`).

## Offline / provider-neutral discipline

- `_NoNetwork` patches `socket.socket` so any network call raises.
- The fake classifier fixture carries **no** provider/model/region field; the
  routing policy has no provider parameter, so routes are provider-free.
- No paid provider, no OpenRouter/Bedrock, no live Core classifier.

## Gold-label policy (owner decisions F-D1/F-D2/F-D3)

- Every message explicitly authored; `synthetic_only = true`; no real content.
- Two-reviewer reconciliation is modeled as: gold = accepted *spec* behavior for
  hard safety invariants (consequential/multi-intent/bare-affirmative are never
  classifier-eligible; multi-intent never executes); deterministic routes are
  derived from the accepted immutable engine as the regression baseline.
- Mismatches between gold (spec) and engine output are **findings**, not silent
  passes; they are reported, never patched into `src/`.

## Leakage prevention

- Each `near_pair_group` is confined to a single partition; EN/IT translations of
  the same semantic example share the group, so partitions never split a pair.
- Gold labels are external to the engine; the harness recomputes engine output
  fresh each run.

## Threshold sensitivity (no tuning)

`run_evaluation.py` sweeps `informational ∈ {0.50,0.70,0.85,0.90,0.95}` and
`safe_workflow ∈ {0.85,0.90,0.95,1.00}` over eligible-ambiguity cases and confirms
**no consequential threshold path appears** for any hypothetical value. The
accepted thresholds remain the scored configuration; nothing is tuned or
applied.

## Reproducibility

The aggregate report records dataset version/digest, schema version, evaluator
version, Gateway commit, Python version, command, seed, fixture version, and
accepted thresholds. Two identical runs are byte-identical except for the
excluded `generated_utc` timestamp.

## Result

Phase F evaluation is implemented (dataset-v1 / dataset-v1.1, harness, tests).
A bounded safety remediation (Phase F-R, owner authorization 2026-10-02) corrected
PHASEF-DEFECT-1 (policy clarification typing), the IT hypothetical-anchor gap,
straight single-quote masking, the metalinguistic quotation-framing rule, and
contextual Italian clitic multi-intent, and versioned five gold labels. The
corrected, authoritative result and verdict are in `reports/phase_f_closure_report.md`.
