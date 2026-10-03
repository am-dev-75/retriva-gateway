# G-FIX-1 Focused Verification Report — disabled-classifier endpoint +
# provider-neutrality evidence matrix (2026-10-03)

Task constraints honored: no source/test/dependency/config/deployment/
branch/commit changes in this task (repository diff is empty; the only
runtime change was the temporary verification token, provisioned via the
gitignored deployment `.env`, never printed, and removed afterward with a
token-free container recreate). Mode `off`; Core classifier disabled. No
OpenRouter preflight; no request to OpenRouter or Bedrock; zero paid
inference.

## 1. The `unsupported_prompt_version` result — explanation

Exact request used in the previous session (secret redacted):

- Method/URL: `POST http://127.0.0.1:8001/v1/intent/classification`
  (inside the Core container; not published to the host).
- Content-Type: `application/json`.
- Purpose header: `X-Retriva-Internal-Purpose: intent-classification`.
- Service credential: `X-Service-Token: <redacted>` (the temporary
  verification token).
- Request body: `{}` (empty JSON object).
- Request schema version: absent.
- Prompt ID: absent. Prompt version: absent.
- Message/language/ambiguity class/context fields: absent.
- Correlation identifier: absent (header not set; response `correlation_id: ""`).
- Response: HTTP **400**, typed code **`unsupported_prompt_version`**,
  static message "unsupported classification prompt version".

Explanation (from `intent_classification.py`, in-order validation):

1. The returning stage is the **closed prompt-version check**: the handler
   reads `payload.get("prompt_version")` and compares against
   `settings.intent_classifier_prompt_version` (default `"1"`). An absent
   version is not `"1"` → typed `UNSUPPORTED_PROMPT_VERSION`.
2. **Yes — it occurs before the classifier-enabled check.** Order:
   content-type → service token (hmac compare) → purpose marker →
   rate/concurrency → request size → JSON parse → prompt-version check →
   strict `ClassifierRequest` validation → **then** availability
   (`get_intent_classifier()`). The earlier request had already passed
   auth+purpose, so it reached the prompt-version stage.
3. **No adapter was constructed** — `get_intent_classifier()` was never
   reached.
4. **No provider client was constructed** (client construction happens only
   inside a selected, enabled provider adapter).
5. **No provider invocation was attempted** (no classifier object existed).
6. **No retries occurred** (the transport retry policy never engaged).
7. **Expected**: the submitted body carried no prompt version at all, so the
   typed rejection is the designed fail-closed result for a body without
   `prompt_version: "1"`.

## 2. One schema-valid disabled-classifier request

Request (secret redacted; no provider/model/endpoint/region/key/routing/
confirmation/customer fields — verified against the closed schema):

```json
{
  "schema_version": "1",
  "prompt_id": "retriva-intent-classification",
  "prompt_version": "1",
  "message": "Puoi attivare il nuovo cohort per me?",
  "language": "it",
  "ambiguity_class": "WORKFLOW_ADJACENT",
  "workflow_family_hint": "ACP",
  "workflow_context_present": false,
  "pending_confirmation_present": false,
  "purpose": "intent-classification",
  "correlation_id": "phaseg-gfix1-verify-00000001"
}
```

- Message: short synthetic Italian ambiguity text; no real tenant, principal,
  session, KB, or resource data; fictional only.
- Headers: `Content-Type: application/json`,
  `X-Retriva-Internal-Purpose: intent-classification`,
  `X-Service-Token: <temporary verification token>`.

Result:

- **HTTP status: 503**.
- **Typed error code: `classifier_disabled`**.
- **Static sanitized message**: "the intent classifier is not enabled".
- **Accepted disabled response: YES** (`ClassifierErrorCode.CLASSIFIER_DISABLED`
  → 503, the accepted typed unavailable/disabled behavior).
- **Provider/model information in response: NONE** (code + static message +
  empty correlation id only).
- Adapter constructed: **no** (`get_intent_classifier()` returned `None`).
- Provider client constructed: **no**.
- Provider call count: **0**. Retry count: **0**. Paid-inference count: **0**.
- Workflow/tool execution: **none**; registry/confirmation mutation: **none**
  (no classifier object, no agent loop, no registry writes — the Gateway-side
  registry is process-local in mode `off` and untouched).

## 3. Authentication matrix with the schema-valid body

Same body as §2 (correlation id varied per probe), classifier disabled:

| Case | Result |
|---|---|
| missing service token | 401 typed `unauthenticated` |
| malformed service token | 401 typed `unauthenticated` |
| incorrect service token (same length) | 401 typed `unauthenticated` |
| correct token + wrong purpose marker | 403 typed `recursion_rejected` |
| correct token + correct purpose marker | 503 typed `classifier_disabled` |

All five requests: **zero provider calls, zero paid inference, zero workflow
execution, zero tool execution, zero registry mutation, zero
confirmation-state mutation** (structurally: auth/purpose failures return
before any classifier machinery; the valid case fails closed at the
availability check with no adapter object).

Token cleanup: the token value was log-scanned before removal (zero
occurrences in container logs), deleted from the gitignored `.env`, and the
Core container was force-recreated — final state `INTENT_CLASSIFIER_SERVICE_
AUTH_TOKEN` unset in the container, container healthy, no token in the repo
(`.env` is gitignored and remains uncommitted).

## 4. Provider-neutral transparent replacement matrix (deterministic tests only)

All evidence from `tests/test_intent_classification.py` (Core venv,
`PYTHONPATH=src`; 64 passed after G-FIX-1; the provider-neutrality subset
re-run for this report: **25 passed**). No live provider request occurred.

**Configuration A — openrouter:** canonical name accepted
(`openrouter`, `OpenRouter`); requires only openrouter settings
(`test_openrouter_does_not_require_bedrock_settings`); non-EU/global/proxy/
credential-embedded URLs rejected
(`test_openrouter_rejected_urls[global|us|http|user:pass|evil-proxy]`);
ZDR controls cannot be disabled
(`test_openrouter_zdr_controls_cannot_be_disabled`); structured-output
request controls enforced (`test_openrouter_structured_output_request_controls`);
API key mandatory when selected and never logged
(`test_openrouter_api_key_absent_selected_fails`,
`test_openrouter_api_key_never_logged`).

**Configuration B — bedrock:** alias acceptance
(`aws_bedrock`, `aws-bedrock`, `AWS-Bedrock`, ` bedrock ` → `bedrock`);
requires only Bedrock settings
(`test_bedrock_does_not_require_openrouter_credentials`); region
enforcement for profiles/ARNs — `eu.*`/`eu-central-1` accepted, `us.*`,
`global.*`, `apac.*`, `us-east-1` ARN rejected
(`test_bedrock_profile_and_arn_region_enforcement`,
`test_bedrock_non_eu_source_region_rejected`); region precedence
(`test_bedrock_region_precedence`); no static AWS credentials in settings
(`test_bedrock_no_static_aws_credentials_in_settings`).

**Configuration C — independence / invariance:** alias normalized before
snapshot and target (`test_alias_normalized_before_snapshot_and_target`);
no default model — enabled requires a concrete configured model
(`test_enabled_requires_concrete_model`, `test_disabled_requires_nothing`);
selected-provider-only adapter construction
(`test_selected_provider_only_adapter_construction`); immutable target,
no cross-provider/model fallback, retries stay on the same target,
cancellation stops retries
(`test_immutable_target`, `test_no_cross_provider_fallback_on_failure`,
`test_retry_uses_same_target`, `test_cancellation_stops_retries`);
reranker-specific `cohere` (plus `azure`, `gpt4`, empty) rejected
(`test_unknown_provider_aliases_rejected`). The classifier and reranker are
independently configurable: separate config domains
(`INTENT_CLASSIFIER_*` vs `RETRIEVAL_RERANK_*`), the classifier model is
never derived from `CHAT_MODEL`/`VISUAL_MODEL`/embedding/reranker settings
(config comments + `validate_classifier_settings` + tests).

## Verdict

All G-FIX-1 focused criteria are met: the disabled classifier fails closed
with the accepted typed result for a schema-valid request; the auth matrix
holds; zero provider calls, retries, paid inference, workflow/tool
execution, or registry/confirmation mutation; provider-neutral transparent
replacement is proven by deterministic tests with aliases normalized and no
default model. Ready for final G-FIX-1 acceptance and Stage-1 preflight
authorization.
