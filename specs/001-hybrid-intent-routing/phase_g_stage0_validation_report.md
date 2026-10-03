# Phase G Validation Report — Stage 0 (mode off) — 2026-10-03

Phase G authorization: owner message 2026-10-03 (G-D1 limited live paid
inference; G-D2 OpenRouter / `qwen/qwen3.5-27b` EU endpoint; preflight,
paid-use cap 500 requests / EUR 10, single-replica topology, staged
rollout off → Stage 1 smoke → Stage 2 shadow; active mode NOT authorized).

Entry proposal commit: `ff3ab11` (documentation-only, verified).
Gate F accepted commits: `377cfde`, `ddc7697`, `b52e0c4`, `f9210ab`,
`4336588` — none amended, squashed, rebased, merged, or pushed.
Gateway suite baseline re-verified pre-implementation:
700 collected / 697 passed / 3 failed / 0 skipped (exit code nonzero;
the three accepted baseline failures only).

## Stage 0 result

| Check | Result |
|---|---|
| One Gateway replica, one Core replica | PASS (compose project `cust_0007`) |
| Core and Gateway healthy | PASS (both `healthy`, `/gateway/health` 200) |
| No failed migrations / startup errors | PASS (clean startup logs; secrets redacted) |
| Router mode | `off` (default; no env override) |
| Classifier state | disabled (`AGENT_INTENT_CLASSIFIER_ENABLED=false`, `INTENT_CLASSIFIER_ENABLED` unset) |
| Internal endpoint authentication | PASS: unauthenticated 401; wrong token 401; CORS preflight 400 (no CORS); valid internal token 200 |
| Status endpoint content | PASS: 537-byte bounded, content-free response (`mode`, metrics counters, registry counts, shadow ring summary, classifier policy facts only) |
| Legacy routing smoke (mode off) | PASS: `POST /gateway/chat` → legacy grounded-RAG behavior, HTTP 200 |
| Classifier call count | PASS: zero (no classifier counters; `classifier_latency.count = 0`) |
| Secret leakage | PASS: no secret values printed, logged, or exposed through status |
| Monitoring operational | PASS (auth-protected `/gateway/internal/routing/status`) |

Rollback: the deployed instance is already in mode `off` (the rollback
state); the off → shadow → off rollback switch will be proven on the
deployed instance when shadow configuration is first applied.

No deployment or live-provider action occurred before the entry
authorization; no paid inference has occurred in Stage 0 and none can
occur while the classifier is disabled.

## BLOCKER (fail-closed): retriva-core runtime dependency gap

The Core image rebuild from the accepted branch
(`phase-d-classifier-transport` @ `8bbe100`) fails at startup:

```
src/retriva/openai_api/routers/intent_classification.py:69
from loguru import logger
ModuleNotFoundError: No module named 'loguru'
```

`loguru` is imported by the accepted Phase D classification router but
is not declared in `retriva-core/requirements.txt` (verified: no match
in `requirements*.txt`, `pyproject.toml`). The Gate D/F validation
virtualenv had it available, so all accepted suites passed; the
container image fails at import.

Remediation requires editing `retriva-core/requirements.txt` (runtime
source, read-only under this Phase G authorization). Per the
authorization rule ("If a runtime code change appears necessary, stop
and return BLOCKED: OWNER DECISION REQUIRED"), the Core image rebuild
is stopped, the stack was restored healthy on the previous working
Core image (2026-10-01), and no fallback or workaround was applied.

**BLOCKED: OWNER DECISION REQUIRED** for Stage 1 entry (classifier
enabled): the Core image containing the accepted Phase D classifier
transport cannot be built until the owner authorizes the one-line
dependency declaration (add `loguru` to `retriva-core/requirements.txt`,
or an equivalent owner-chosen remedy). Stage 0 exit criteria are met
with the current stack; no classifier message has been sent; the G-D2
preflight and paid-use cap are recorded and pending Stage 1.
