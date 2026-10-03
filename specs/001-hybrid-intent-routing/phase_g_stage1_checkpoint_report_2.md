# Phase G Stage 1 Checkpoint Report — fresh cycle (2026-10-03)

## Verdict

**BLOCKED: PHASE G PREREQUISITES NOT MET**

Per the standing Stage-1 rule (model eligibility failure): the exact
selected model `qwen/qwen3.5-27b` has no eligible EU/ZDR/structured-output
endpoint at the time of Phase G validation. Metadata preflight was
insufficient, and the authorized first synthetic capability request was
rejected fail-closed by the provider under the mandated immutable routing
constraints. Per the rule: no further classifier requests were sent; no
model substituted; no Bedrock invocation; no global/US OpenRouter access;
mode retained `off`; the classifier is disabled again. A different model
requires a separate owner decision.

## 1. Starting branches, commits, and clean states

| Repository | Branch | HEAD | Tree |
|---|---|---|---|
| retriva-core | `phase-g-classifier-packaging-fix` | `18e71bf` (accepted G-FIX-2) | clean |
| retriva-gateway | `phase_f_evaluation` | `88d03c2` | clean |
| retriva-local-containerized-deployment | `phase-d-classifier-env` | `ac37d4f` | clean |
| retriva-crm-assistant | `phase-c-activation-idempotency` | `88dccf4` | clean |

No accepted commit amended/squashed/rebased/merged/pushed; no new commits
created during this cycle (the checkpoint report is the only new
documentation commit).

## 2. G-FIX-1/G-FIX-2 acceptance baseline

Both accepted (`6fffb13`, `18e71bf` + evidence `009679b`, `88d03c2`).
Starting deployed state: mode `off`, classifier disabled, stack healthy.

## 3. Deployment topology and replica proof

Compose project `cust_0007`: exactly one `retriva-gateway` + one
`retriva-core` container; both healthy before, during, and after the
cycle. Gateway `AGENT_INTENT_ROUTER_MODE` unset (default `off`) and
`AGENT_INTENT_CLASSIFIER_ENABLED=false` throughout — **no production
request could invoke the classifier**.

## 4. Exact provider/model configuration (as mandated)

Applied temporarily to the gitignored deployment `.env` (removed after
the cycle):

```
INTENT_CLASSIFIER_ENABLED=true (temporary, Stage 1 only)
INTENT_CLASSIFIER_PROVIDER=openrouter
INTENT_CLASSIFIER_MODEL=qwen/qwen3.5-27b
INTENT_CLASSIFIER_OPENROUTER_BASE_URL=https://eu.openrouter.ai/api/v1
INTENT_CLASSIFIER_REQUIRE_EU_RESIDENCY=true
INTENT_CLASSIFIER_REQUIRE_ZDR=true
INTENT_CLASSIFIER_OPENROUTER_ZDR=true
INTENT_CLASSIFIER_OPENROUTER_DATA_COLLECTION=deny
INTENT_CLASSIFIER_OPENROUTER_REQUIRE_PARAMETERS=true
INTENT_CLASSIFIER_OPENROUTER_ALLOW_FALLBACKS=false
INTENT_CLASSIFIER_OPENROUTER_API_KEY=<existing account key value; never
  printed, logged, or committed>
INTENT_CLASSIFIER_SERVICE_AUTH_TOKEN=<fresh random token; never printed,
  logged, or committed>
```

Classifier-enabled startup succeeded cleanly (G-FIX-2 proven in the
serving container) — strict startup validation passed with no errors.

## 5. Model-capability preflight evidence (metadata-only, no charge)

- `GET https://eu.openrouter.ai/api/v1/models/qwen/qwen3.5-27b/endpoints`:
  the model id resolves ("Qwen: Qwen3.5-27B") but **`endpoints: []`** —
  no per-endpoint metadata (serving region, ZDR, quantization,
  structured-output parameters) is exposed.
- `GET https://eu.openrouter.ai/api/v1/models`: catalog of 70 models;
  **`qwen/qwen3.5-27b` is not listed**; no supported-parameters or pricing
  data for it.
- Conclusion: metadata **cannot** prove EU-serving, ZDR,
  data-collection=deny, or structured-output eligibility. Per the
  authorization, the next permitted step was the single fail-closed
  synthetic capability request.

## 6. EU endpoint and residency evidence

Structural (accepted Phase D tests + adapter code): the adapter
constructor rejects any non-EU base URL under required residency; global
and US endpoints rejected; HTTPS-only, no embedded credentials. The live
request used the exact EU base URL; the rejection came back typed, with
no endpoint change and no fallback (see §16).

## 7. ZDR and data-collection evidence

Structural: `zdr: true` and `data_collection: "deny"` are embedded in the
immutable provider preference block of every classifier request
(`providers/openrouter.py::_build_payload`), and accepted tests prove
these controls cannot be disabled. Runtime confirmation of a serving
endpoint honoring them was **not obtainable**: the provider rejected the
single request under exactly these constraints (fail-closed).

## 8. Secret provisioning and cleanup

Two temporary secrets provisioned via the gitignored deployment `.env`
only (values never printed/logged/committed): the OpenRouter key
reference and a fresh random `INTENT_CLASSIFIER_SERVICE_AUTH_TOKEN`.
Log-scan during the cycle: **0 occurrences** of either value in container
logs. End state: the Stage-1 block was removed from `.env` (pre-cycle
backup restored), the container force-recreated — container env clean
(`INTENT_CLASSIFIER_*` unset), `.env` still untracked.

## 9. Internal endpoint authentication proof

The single live request used the dedicated internal service token +
accepted purpose marker and passed auth (reaching the classifier path).
Re-confirmed disabled-state matrix from G-FIX-1 remains in force (401 /
403 typed rejections; status endpoint auth verified in Stage 0).

## 10. Exact synthetic test corpus categories

Only **one** live request was sent (capability test, EN non-adjacent
informational ambiguity: "I want to see how the new activation works.",
fictional correlation id `stage1-cap-0000000001`). The full smoke-test
coverage matrix (EN/IT informational + safe-workflow ambiguity,
low-confidence clarification, quoted/hypothetical consequential,
multi-intent, consequential candidate, prompt-injection, fake
override-attempt, malformed-response, timeout, regional failure) was
**not executed** — prohibited by the eligibility-failure rule
("send no further classifier requests").

## 11. Exact request count

**1 live classifier request** (cap: 500). Zero subsequent requests.

## 12. Cost estimate and provider-reported usage

The request was rejected before any completion was produced (typed
`provider_rejected`); **estimated cost EUR 0**. No provider usage record
is available for a rejected request; local counter: 1 request, 0
successful completions. Far under the EUR 10 cap.

## 13. Success and typed-failure counts

- Successful structured classifications: **0**.
- Typed failures: **1** — HTTP **500**, code **`provider_rejected`**,
  static sanitized message "classification provider rejected the request"
  (no provider error body, no endpoint/model info, empty correlation id).
- The result is the designed fail-closed capability rejection: with
  `allow_fallbacks=false`, `require_parameters=true`, `zdr=true`,
  `data_collection=deny`, and EU-only routing, the provider has no
  endpoint able to serve `qwen/qwen3.5-27b` — instead of silently serving
  an ineligible endpoint or model, it rejects.

## 14. Latency summary

Not meaningful (single rejected request); the rejection returned
promptly (well under the 10 s p95 threshold). No latency threshold
breach.

## 15. Structured-output validation result

No structured response was produced (provider rejection), so local strict
validation had nothing to validate; the local strict C2 validation path
remains proven by the accepted deterministic tests (64 focused tests,
including strict-response handling).

## 16. No-fallback proof

The single request: exact EU base URL (`https://eu.openrouter.ai/api/v1`);
exact configured model; **no** global/US endpoint; **no** alternate model;
**no** alternate provider; **no** Bedrock call; **no** chat/visual/reranker
fallback. Evidence: the adapter embeds the immutable preference block and
the transport target is immutable (accepted tests
`test_immutable_target`, `test_no_cross_provider_fallback_on_failure`,
`test_retry_uses_same_target`); the typed rejection (not a silent
different-endpoint success) is itself the no-fallback proof at runtime.

## 17–18. No-tool, no-mutation, no-confirmation-state-mutation proof

No workflow executed; no tool executed; no registry or confirmation
mutation (the request never produced a classification; Gateway mode `off`
with its classifier disabled and no production traffic processed).

## 19. Privacy and logging proof

No raw prompt or provider response persisted anywhere; the response
artifact is the typed, sanitized error only. Log-scan: 0 occurrences of
either secret value in container logs; no provider error body in logs;
no request headers logged.

## 20. Request and response schema proof

The request used the accepted closed schema (schema_version "1",
prompt_id `retriva-intent-classification`, prompt_version "1", closed
language/ambiguity-class/context fields, synthetic correlation id,
purpose marker). The response was the closed typed error envelope. No
provider/model/endpoint/region/authorization/tool fields appeared in
either direction.

## 21. Health and readiness results

Classifier-enabled startup (G-FIX-2): clean, strict validation passed.
After restore: Core and Gateway healthy (200), classifier disabled.

## 22. Rollback result

Executed and verified: Stage-1 env block removed; container recreated
token-free and classifier-disabled; zero `INTENT_CLASSIFIER_*` variables
in the container; Core + Gateway health 200/200; mode `off` preserved.

## 23. Mode remained off for production routing

Yes — Gateway `AGENT_INTENT_ROUTER_MODE` unset (default `off`) throughout
the entire cycle; classifier enablement existed only in the Core
container env, and the only path exercised was the direct authenticated
internal endpoint with synthetic content.

## 24. No production user traffic processed

Confirmed — no production user traffic invoked the classifier (Gateway
classifier disabled; mode `off`).

## 25. Stage 2 not started

Confirmed — no shadow configuration applied; no paid shadow traffic; no
owner checkpoint for Stage 2 was requested or due.

## 26. Final Git and deployment states

- All repositories clean at the same HEADs as §1 (no runtime commits; the
  Stage-1 report is documentation-only in retriva-gateway).
- Deployment: pre-cycle `.env` restored; Core healthy, classifier
  disabled; Gateway healthy, mode `off`; zero classifier calls
  outstanding.
- Total live classifier requests across the whole Stage-1 fresh cycle: 1
  (rejected); total paid inference: EUR 0.

## 27. Incidents, blockers, prerequisites

- **Incident:** single typed fail-closed provider rejection on the
  capability request (handled per procedure; no stop-condition breach —
  rejection rate 100% of 1, but the eligibility rule applies before
  rate thresholds).
- **Blocker:** `qwen/qwen3.5-27b` has no eligible EU/ZDR/structured-output
  endpoint (metadata: no endpoints listed, not in EU catalog; runtime:
  fail-closed provider rejection under the mandated constraints).
- **Prerequisite for continuing:** a separate owner decision selecting a
  different classifier model (no substitution performed; no requirement
  weakened).

## 28. Verdict

**BLOCKED: PHASE G PREREQUISITES NOT MET** — model eligibility failure
under the standing Stage-1 rule; awaiting a separate owner decision on
the classifier model (Stage 2 not entered).
