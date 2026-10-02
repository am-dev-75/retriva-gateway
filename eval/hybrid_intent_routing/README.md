# Phase F Evaluation Dataset — README

Synthetic, English/Italian, privacy-safe evaluation corpus for the accepted
Gateway hybrid-intent routing policy (Spec 001 / ADR-0002). Built and run
**offline**; no network, no live provider, no paid inference.

## Files

| File | Purpose |
|------|---------|
| `dataset-schema-v1.json` | closed gold-label schema (single source of truth) |
| `dataset-v1.jsonl` | 109 explicit synthetic records (EN/IT); preserved byte-for-byte |
| `dataset-v1.1.jsonl` | versioned gold-label correction of 5 conclusively invalid labels (F-R4) |
| `build_dataset.py` | authors cases and derives gold from the accepted engine |
| `validate_dataset.py` | schema + cross-field + privacy + leakage validation |
| `run_evaluation.py` | offline evaluation harness; asserts safety invariants |
| `gate-f-thresholds-v1.json` | pre-registered Gate F quality thresholds (F-R7) |
| `phase_f_metrics_draft.json` | provenance-only draft (renamed from expected-metrics.json) |
| `CHANGELOG.md` | dataset gold-label + metric-reconciliation changelog |
| `reports/` | generated aggregate reports (incl. corrected closure report) |

## Reproduce

```bash
export PYTHONPATH=src:/path/to/retriva-core/src:/path/to/retriva-crm-assistant/src
python eval/hybrid_intent_routing/build_dataset.py
python eval/hybrid_intent_routing/validate_dataset.py
python eval/hybrid_intent_routing/run_evaluation.py \
    --dataset eval/hybrid_intent_routing/dataset-v1.1.jsonl \
    --out eval/hybrid_intent_routing/reports/evaluation_report.json
python -m pytest tests/eval/ -q -p no:cacheprovider
```

## Dataset facts

- **109 records**, languages `en=56 / it=53`.
- All 18 required case families present, each with EN/IT balance.
- `schema_version = 1`; `synthetic_only = true` on every record.
- No real company/customer/email/key/URL content (validator scans for markers).
- Near-pairs grouped so no partition splits a pair (leakage-controlled).

## Privacy & data minimization

Messages use only fictional, structurally synthetic identifiers
(`acpver_123`, `cohver_9`, `batch_77`, `ench_12`, `proposal_5`). No production
messages, logs, shadow records, or confidential content are used (owner
decision F-D2).

## Status

Dataset valid and leakage-controlled (`dataset-v1.jsonl` preserved; `dataset-v1.1.jsonl`
applies five owner-approved gold-label corrections, F-R4). After the bounded Phase F-R
remediation, all non-negotiable safety-zero metrics are zero; Gate F remains blocked
on near-pair consistency for five deferred groups (owner decision F-R5). See
`reports/phase_f_closure_report.md`.
