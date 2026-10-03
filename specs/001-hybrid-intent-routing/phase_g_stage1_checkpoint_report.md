# Phase G Stage 1 Checkpoint Report — BLOCKED: OWNER DECISION REQUIRED
# (2026-10-03)

## 1. Starting branches, commits, and clean states

| Repository | Branch | HEAD | Tree |
|---|---|---|---|
| retriva-core | `phase-g-classifier-packaging-fix` | `6fffb13` | clean |
| retriva-gateway | `phase_f_evaluation` | `009679b` | clean |
| retriva-local-containerized-deployment | `phase-d-classifier-env` | `ac37d4f` | clean |
| retriva-crm-assistant | `phase-c-activation-idempotency` | `88dccf4` | clean |

No accepted commit was amended, squashed, rebased, merged, or pushed.
No new commits were created during Stage 1.

## 2. G-FIX-1 acceptance baseline

Accepted: retriva-core `6fffb13` (logging-dependency correction) and
retriva-gateway `009679b` (focused verification evidence). Starting state
verified: mode `off`, classifier disabled (both sides), stack healthy.

## 3. Deployment topology and replica proof

Compose project `cust_0007`: exactly **one** `retriva-gateway` and **one**
`retriva-core` container (both healthy); single replica verified by
`docker ps` counts before and after all actions. Gateway mode `off`;
`AGENT_INTENT_CLASSIFIER_ENABLED=false` throughout — no production request
can invoke the classifier.

## 4. Exact provider/model configuration (as mandated by G-D2/Stage 1)

Applied temporarily to the gitignored deployment `.env` (not committed):

```
INTENT_CLASSIFIER_ENABLED=true
INTENT_CLASSIFIER_PROVIDER=openrouter
INTENT_CLASSIFIER_MODEL=qwen/qwen3.5-27b
INTENT_CLASSIFIER_OPENROUTER_BASE_URL=https://eu.openrouter.ai/api/v1
INTENT_CLASSIFIER_REQUIRE_EU_RESIDENCY=true
INTENT_CLASSIFIER_REQUIRE_ZDR=true
INTENT_CLASSIFIER_OPENROUTER_ZDR=true
INTENT_CLASSIFIER_OPENROUTER_DATA_COLLECTION=deny
INTENT_CLASSIFIER_OPENROUTER_REQUIRE_PARAMETERS=true
INTENT_CLASSIFIER_OPENROUTER_ALLOW_FALLBACKS=false
INTENT_CLASSIFIER_OPENROUTER_API_KEY=<reference to the existing OpenRouter
  account key value; never printed or committed>
INTENT_CLASSIFIER_SERVICE_AUTH_TOKEN=<temporary random token; never
  printed or committed>
```

The model is deployment-global configuration only; nothing hard-coded;
not derived from CHAT_MODEL/other settings (Core validation enforces this).

## 5. Model-capability preflight evidence (metadata-only, no inference)

`GET https://eu.openrouter.ai/api/v1/models/qwen/qwen3.5-27b/endpoints`
(non-content-bearing, unauthenticated metadata read; no inference charge):

- model id resolves: `qwen/qwen3.5-27b` ("Qwen: Qwen3.5-27B");
- **`endpoints: []` — the EU host exposes NO per-endpoint metadata**;
- `GET /api/v1/models` on the EU host: 70 models, `qwen/qwen3.5-27b`
  **not in the catalog**, no `supported_parameters`/pricing data.

Conclusion: **current OpenRouter metadata cannot prove** EU-serving,
ZDR, data-collection=deny, or structured-output support for the exact
model. Per the Stage 1 authorization, the next permitted step was the
bounded synthetic smoke test with the first request as a fail-closed
capability test — because the adapter sends
`allow_fallbacks=false, require_parameters=true, zdr=true,
data_collection=deny` (verified in
`providers/openrouter.py::_build_payload`), so an ineligible model cannot
be silently served. **That step was never reached** (see §27/§28: the
classifier-enabled startup crashed before any request).

## 6–7. EU endpoint / residency / ZDR evidence

Structural (code) evidence only, from the accepted Phase D tests: the
adapter constructor rejects any base URL other than the EU endpoint under
required residency; global/US endpoints rejected; ZDR controls cannot be
disabled. No live residency/ZDR runtime evidence exists because no
classifier request was sent.

## 8. Secret provisioning and cleanup

Two temporary secrets were provisioned via the **gitignored** deployment
`.env` only: `INTENT_CLASSIFIER_OPENROUTER_API_KEY` (reference to the
existing OpenRouter account key; value never printed/logged/committed) and
`INTENT_CLASSIFIER_SERVICE_AUTH_TOKEN` (fresh random value). After the
stop, the entire Stage-1 block was removed from `.env` (backup of the
pre-Stage-1 file restored) and the Core container was force-recreated;
the container env is clean (`INTENT_CLASSIFIER_*` unset). `.env` remains
untracked (gitignored); no secret entered any repo, log, or report.

## 9. Internal endpoint authentication proof

Re-verified during G-FIX-1 and Stage-0 state (classifier disabled): valid
token → typed `classifier_disabled` (503); missing/malformed/incorrect →
401; wrong purpose marker → 403 `recursion_rejected`.

## 10–25. Smoke-test coverage, counts, cost, latency, proofs

**Not executed.** The classifier could not be enabled: Core startup
crashed before serving any request (see §27). Consequently: live request
count **0**; provider-reported usage **0**; cost **0 EUR**; success/typed-
failure counts **0 live**; latency data **none**; no-fallback proof is
structural only (adapter payload + config validation); no-tool /
no-mutation / no-confirmation-mutation proofs hold trivially (no request
processed, mode `off` throughout, Gateway classifier disabled); no raw
prompt/response persisted (nothing existed); production routing remained
`off`; no production user traffic processed; Stage 2 not started.

## 22. Rollback result

Executed: Stage-1 env block removed, container recreated token-free and
classifier-disabled, **Core and Gateway healthy after rollback**
(health 200/200), mode `off` preserved.

## 26. Final Git and deployment states

- Repositories: exactly as in §1 (clean, HEADs unchanged; no new commits).
- Deployment: pre-Stage-1 `.env` restored; Core healthy with classifier
  disabled; Gateway healthy, mode `off`; zero `INTENT_CLASSIFIER_*`
  variables in the Core container env.
- Zero paid inference across the whole Stage 1 attempt.

## 27. Incident / blocker

**Incident (fail-closed, immediate stop): classifier-enabled Core startup
crashes with a circular import.**

Exact traceback (from `docker logs retriva-core` at startup with
`INTENT_CLASSIFIER_ENABLED=true`):

```
File "/app/src/retriva/openai_api/main.py", line 19
    from retriva.openai_api.routers import intent_classification
...
ImportError: cannot import name 'settings' from partially initialized
module 'retriva.config' (most likely due to a circular import)
(/app/src/retriva/config.py)
```

Chain: `retriva.config.model_post_init` (the classifier-**enabled**
validation branch, added in accepted Phase D) imports
`retriva.intent_classification.base` → the package `__init__` imports
`factory` → `factory` imports `retriva.config` (module-level) →
`retriva.config` is still mid-initialization → `ImportError`.

Why the accepted suites never caught it: every accepted test runs with the
classifier disabled or validates via direct function calls; the
enabled-at-startup path (settings constructed with
`intent_classifier_enabled=true` through `model_post_init`) is exercised
only by real deployment startup. This is a **runtime source defect in
retriva-core** — read-only under the Stage 1 authorization ("If a runtime
code change appears necessary, stop and return BLOCKED: OWNER DECISION
REQUIRED. Do not patch runtime behavior during rollout.").

Immediate-stop procedure was executed: classifier disabled, mode `off`,
no synthetic traffic was generated, no credentials retained, content-free
evidence only (this report), zero classifier calls, healthy legacy
behavior verified.

**Minimal candidate fix (owner decision required, not applied):** in
`retriva-core/src/retriva/intent_classification/factory.py`, replace the
module-level `from retriva.config import settings` with a function-local
(lazy) import (≈2-line change), or equivalently defer the
`intent_classification` import inside `config.model_post_init`. The
accepted Phase D tests would be re-run plus a new enabled-startup test;
then a Core image rebuild + Stage-1 restart of the bounded authorization.

## 28. Verdict

**BLOCKED: OWNER DECISION REQUIRED**

Reason: enabling the classifier — the mandatory first step of Stage 1 —
requires a runtime source correction in `retriva-core` (circular import in
the classifier-enabled settings-validation path), which the Stage 1
authorization forbids (runtime is read-only; no patching during rollout).
No classifier request was sent; no provider invocation, retry, or paid
inference occurred; the stack is healthy in mode `off` with the classifier
disabled.
