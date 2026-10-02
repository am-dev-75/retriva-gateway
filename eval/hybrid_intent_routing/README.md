# Phase F Evaluation Dataset — README

Synthetic, English/Italian, privacy-safe evaluation corpus for the accepted
Gateway hybrid-intent routing policy (Spec 001 / ADR-0002). Built and run
**offline**; no network, no live provider, no paid inference.

## Files

| File | Purpose |
|------|---------|
| `dataset-schema-v1.json` | closed gold-label schema (single source of truth) |
| `dataset-v1.jsonl` | 113 explicit synthetic records (EN/IT) |
| `build_dataset.py` | authors cases and derives gold from the accepted engine |
| `validate_dataset.py` | schema + cross-field + privacy + leakage validation |
| `run_evaluation.py` | offline evaluation harness; asserts safety invariants |
| `expected-metrics.json` | committed Gate F evidence (thresholds + results) |
| `reports/` | generated aggregate reports |

## Reproduce

```bash
export PYTHONPATH=src:/path/to/retriva-core/src:/path/to/retriva-crm-assistant/src
python eval/hybrid_intent_routing/build_dataset.py
python eval/hybrid_intent_routing/validate_dataset.py
python eval/hybrid_intent_routing/run_evaluation.py \
    --dataset eval/hybrid_intent_routing/dataset-v1.jsonl \
    --out eval/hybrid_intent_routing/reports/evaluation_report.json
python -m pytest tests/eval/ -q -p no:cacheprovider
```

## Dataset facts

- **113 records**, languages `en=58 / it=55`.
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

Dataset valid and leakage-controlled. Evaluation surfaces accepted-engine gaps
(documented in `expected-metrics.json` and the closure report); Gate F is
**BLOCKED: GATE F CRITERIA NOT MET** pending owner decisions.
