# G-FIX-1 Verification Report — Core classifier packaging correction

Authorization: owner message 2026-10-03 (bounded prerequisite correction;
Stage 0 accepted; Stage 1 remains blocked until this correction is
implemented, verified, and explicitly accepted).

## Constraints honored

- `AGENT_INTENT_ROUTER_MODE=off` throughout; classifier disabled throughout.
- No OpenRouter eligibility preflight; no classifier prompt; no live provider
  call; zero paid inference.
- No Gateway runtime change; no deployment configuration change committed;
  no provider/model selected; GF-001 untouched.

## Starting state (recorded before editing)

- Core branch `phase-d-classifier-transport`, HEAD `8bbe100`, clean tree;
  `8bbe100` verified ancestor of HEAD.
- Accepted commits immutable: `8172dd1`, `8bbe100` (Core Phase D tips),
  `fb3acbc`, and the Gateway Gate F lineage (`377cfde`, `ddc7697`, `b52e0c4`,
  `f9210ab`, `4336588`) — none amended, squashed, rebased, merged, or pushed.
- Container build command: `docker compose build retriva-core`
  (context `../retriva-core`, `Dockerfile`, deps from
  `retriva-core/requirements.txt`).
- Failing traceback: `openai_api/main.py` import chain →
  `routers/intent_classification.py:69` → `from loguru import logger` →
  `ModuleNotFoundError: No module named 'loguru'`.
- No live provider request had occurred.

## Correction

Branch `phase-g-classifier-packaging-fix` from `8bbe100` (as recommended).
Commit **`6fffb13`**: 1 file changed, 2 insertions(+), 2 deletions(+) —
`src/retriva/openai_api/routers/intent_classification.py`:
- removed `from loguru import logger`;
- the single `logger.info(...)` call site now uses Core's own logging
  convention (`from retriva.logger import get_logger`;
  `get_logger(__name__).info(...)`), which `setup_logging()` configures at
  startup (same format as the rest of Core's logs).

This is the minimum correction: it removes the undeclared dependency
entirely rather than adding `loguru` to the manifest, keeps the accepted
router behavior, and adds no new dependency surface. Content-free logging
preserved (correlation id, latency, prompt id/version — no message content).

## Provider-neutral interface verification (unchanged by the fix, re-verified)

- Canonical providers: `openrouter`, `bedrock`; aliases `aws_bedrock` /
  `aws-bedrock` normalize to `bedrock` before snapshots/fingerprints/
  adapter construction/logging/status/tests (`base.py` `canonical_provider_name`).
- The reranker's `cohere` alias is explicitly NOT accepted for the classifier.
- No default model: `INTENT_CLASSIFIER_MODEL` is mandatory when the
  classifier is enabled and is never derived from chat/visual/embedding/
  reranker settings (`validate_classifier_settings`).
- No hard-coded model, OpenRouter/Bedrock model, inference profile, provider
  endpoint, or AWS region in the interface, router, prompt, or schema
  (grep-verified); the EU base URL default is configuration, validated at
  startup when enabled.

## Test results (Core venv, `PYTHONPATH=src`)

- Focused: `tests/test_intent_classification.py` — **64 passed**.
- Full Core suite (corrected code): 13 failed, 678 passed, 1 skipped,
  15 errors — all pre-existing environment-dependent baseline.
- Zero-regression control: pristine `8bbe100` cannot even collect in this
  environment (the `loguru` import chain fails at collection); pristine
  `8bbe100` + a loguru stub module (control reproducing the
  loguru-available accepted venv) yields a failure set **IDENTICAL** to the
  corrected code (diff empty). None of the residual failures touches the
  classifier.
- Gateway suite re-confirmed after the change: **700 collected / 697 passed /
  3 failed / 0 skipped** (the three accepted baseline failures only).

## Image rebuild and deployed verification (classifier disabled, mode off)

- `docker compose build retriva-core` from the corrected branch: image built.
- `docker compose up -d retriva-core`: container **healthy** on the corrected
  image; `INTENT_CLASSIFIER_ENABLED` unset (disabled); no startup errors.
- Endpoint auth matrix on the deployed endpoint (temporary random test token
  provisioned via the gitignored deployment `.env` only — value never
  printed, logged, or committed; removed and the container recreated clean
  after validation):

| Case | Result |
|---|---|
| unauthenticated | 401 typed `unauthenticated` |
| missing token | 401 |
| malformed token | 401 |
| incorrect token (same length) | 401 |
| wrong purpose marker (valid token) | 403 typed `recursion_rejected` |
| valid token + correct purpose | 400 typed `unsupported_prompt_version` (auth passed; schema/prompt gate reached; **no inference possible — classifier disabled**) |

- No token value appears in logs (verified by log scan before removal).
- Content-type enforcement precedes auth (non-JSON/missing content type →
  400) — accepted C6 behavior.
- Stack final state: Core and Gateway healthy, mode `off`, classifier
  disabled, token-free environment.

## Result

G-FIX-1 is implemented, verified, and ready for explicit owner acceptance.
Stage 1 remains blocked until that acceptance; the OpenRouter eligibility
preflight and any classifier prompt remain unauthorized and unexecuted.
