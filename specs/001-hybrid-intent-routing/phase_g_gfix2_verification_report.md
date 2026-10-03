# G-FIX-2 Verification Report — classifier-enabled startup circular-import
# correction (2026-10-03)

## Constraints honored

- Production routing mode `off` throughout; deployed classifier disabled
  throughout (the enabled-startup proof ran as a one-shot container with
  no traffic; the serving Core container was recreated disabled).
- No OpenRouter capability preflight; no classifier content sent; no
  OpenRouter/Bedrock invocation; zero paid inference (the one-shot used a
  stub key and sent no request — construction/import only).
- No deployment configuration change committed (`.env` untouched — the
  one-shot used `docker run -e` overrides only).
- Runtime source touched only within the authorized scope.

## Starting state (recorded)

- Core branch `phase-g-classifier-packaging-fix`, HEAD `6fffb13`
  (accepted G-FIX-1 tip), clean tree, `8bbe100` ancestry intact.
- Accepted commits immutable: `6fffb13`, `8bbe100`, `8172dd1` and the
  Gateway Gate F lineage — none amended/squashed/rebased/merged/pushed.
- Stack: Core + Gateway healthy, mode `off`, classifier disabled.

## Root cause (accepted from the Stage 1 checkpoint)

`retriva.config.model_post_init` (classifier-enabled branch) imports
`retriva.intent_classification.base` → package `__init__` imports
`factory` → **module-level** `from retriva.config import settings` in
`factory.py` re-entered the still-initializing `retriva.config` module →
`ImportError: cannot import name 'settings' from partially initialized
module 'retriva.config'`.

## Correction

Branch `phase-g-classifier-packaging-fix`; commit **`18e71bf`**
(`fix(core): lazy settings import in classifier factory breaks
enabled-startup circular import (G-FIX-2)`).

`src/retriva/intention_classification/factory.py` →
`src/retriva/intent_classification/factory.py` (single file,
11 insertions / 1 deletion):

1. The module-level `from retriva.config import settings` was removed and
   replaced by an explanatory comment (why the lazy import exists).
2. `get_intent_classifier()` now performs the settings import lazily
   (function-local) before the enabled check. This runs only after config
   initialization finished, so the cycle is broken.

No interface, schema, validation, policy, factory behavior, error mapping,
or provider-selection change; the factory's build/cache/fingerprint
semantics are untouched.

## Verification

**Python-level (Core venv, `PYTHONPATH=src`):**
- `Settings(...)` with `intent_classifier_enabled=True` constructs
  successfully (previously crashed in `model_post_init`).
- `import retriva.openai_api.main` full chain OK with classifier enabled.
- `get_intent_classifier()` after enabled-settings construction returns
  `OpenRouterIntentClassifier` (selected-provider-only construction;
  `None` when disabled — both verified).

**Deterministic tests (Core venv):**
- Focused `tests/test_intent_classification.py`: **64 passed**.
- Full Core suite: 13 failed, 678 passed, 1 skipped, 15 errors —
  failure set **byte-identical** to the accepted G-FIX-1 baseline
  (`diff` empty against `/tmp/kilo/gfix1_failed.txt`); all residual
  failures pre-existing environment-dependent baseline, none
  classifier-related. Zero new failures, zero changed failures.

**Deployed image proof (one-shot container, no traffic):**
- Core image rebuilt from `18e71bf` (`docker compose build retriva-core`).
- One-shot `docker run` on the compose network with the full Stage-1
  configuration env (`INTENT_CLASSIFIER_ENABLED=true`, provider/model per
  G-D2, EU base URL, EU/ZDR/data-collection/require-parameters/
  no-fallbacks flags; stub key + stub token) and entrypoint `python`:
  - settings construction with classifier **enabled**: OK;
  - full `openai_api.main` import chain (enabled startup): OK;
  - `get_intent_classifier()` → `OpenRouterIntentClassifier` constructed;
  - **no provider request sent; no inference charge** (import/construction
    only; the stub key would be rejected by the provider anyway, and no
    HTTP call was made).

**Restored serving state:**
- Serving Core container recreated with the normal disabled configuration:
  healthy, `INTENT_CLASSIFIER_ENABLED` unset (disabled), mode `off` on the
  Gateway, `/health` 200 on both Core (8201) and Gateway (8202).
- Core repo clean at `18e71bf`; Gateway clean at `009679b`; deployment
  `.env` unmodified by this correction (gitignored, untracked).

## Result

G-FIX-2 is implemented and verified: classifier-enabled Core startup
completes the full import chain and constructs only the selected adapter,
with zero provider requests and zero paid inference. Ready for owner
acceptance; Stage 1 remains blocked until acceptance and a fresh bounded
Stage-1 authorization.
