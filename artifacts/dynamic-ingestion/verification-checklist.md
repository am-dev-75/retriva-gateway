# Dynamic Ingestion — Verification Checklist

## Static checks

- [x] `python -m pytest` — 100 passed, 0 failed
- [ ] `python -m ruff check .` — Not configured in this project
- [ ] `python -m mypy .` — Not configured in this project

## Unit test coverage

| # | Requirement | Test | Status |
|---|---|---|---|
| 1 | Create MediaWiki source | `test_create_mediawiki_source` | ✅ |
| 2 | Reject unsupported connector type | `test_reject_unsupported_connector` | ✅ |
| 3 | Reject invalid MediaWiki API URL | `test_reject_invalid_mediawiki_url` | ✅ |
| 4 | Store `secret_ref`, never raw secret | `test_secret_ref_not_in_response` | ✅ |
| 5 | List sources by tenant | `test_list_sources` | ✅ |
| 6 | Get source status | `test_get_source_status` | ✅ |
| 7 | Pause active/pending source | `test_pause_active_source` | ✅ |
| 8 | Resume paused source | `test_resume_paused_source` | ✅ |
| 9 | Manual sync creates a SourceRun | `test_manual_sync_creates_run` | ✅ |
| 10 | First-sync lifecycle transitions | `test_baseline_to_catchup_to_active` | ✅ |
| 11 | Checkpoint saved after catch-up | `test_checkpoint_saved_after_catchup` | ✅ |
| 12 | Internal endpoints require service auth | `test_internal_auth_required_when_configured` | ✅ |

## Non-functional requirements (§8)

| # | Requirement | Test | Status |
|---|---|---|---|
| 1 | Idempotent source creation | `test_idempotent_create_returns_same_source` | ✅ |
| 2 | Idempotent item upsert | `test_idempotent_item_upsert` | ✅ |
| 3 | Pagination on list endpoints | `test_list_sources_pagination`, `test_list_runs_pagination`, `test_list_items_pagination` | ✅ |
| 4 | Content-free status/telemetry | Verified by code inspection | ✅ |
| 5 | Backward compatibility | All 43 pre-existing tests pass | ✅ |

## Security verification

| # | Requirement | Status |
|---|---|---|
| 1 | No content fields logged by source APIs | ✅ Verified by code inspection |
| 2 | Source config response redacts secret fields | ✅ `test_secret_ref_not_in_response` |
| 3 | Credentials never in persisted source record | ✅ Only `secret_ref` stored |
| 4 | Internal endpoints require service token | ✅ `test_internal_auth_*` |
| 5 | Connector type allowlisted | ✅ `test_reject_unsupported_connector` |

## Additional tests

| Test class | Tests | Coverage |
|---|---|---|
| `TestMediaWikiSourceConfig` | 8 | Config validation (URL, auth_mode, sync interval) |
| `TestSourceInstance` | 2 | Defaults, ID uniqueness |
| `TestSourceResponse` | 2 | Secret redaction |
| `TestSourceRunResponse` | 1 | from_run mapping |
| `TestSourceEnums` | 2 | Enum completeness |
| `TestSourceCrud` | 10 | CRUD operations |
| `TestSourceLifecycle` | 6 | Pause/resume/sync |
| `TestSourceStatus` | 4 | Status + runs |
| `TestFirstSyncLifecycle` | 3 | State machine |
| `TestInternalEndpoints` | 6 | Worker endpoints |
| `TestDisabledDynamicIngestion` | 2 | Feature gating |
| `TestV2RoutePrefix` | 2 | Route aliasing |
| `TestIdempotentSourceCreation` | 3 | Idempotency key |
| `TestPagination` | 3 | List pagination |
| `TestIngestionSessionRunScope` | 2 | Run-scoped sessions |

**Total: 100 tests pass, 0 failures**

## Definition of done

- [x] All tests pass
- [x] API docs updated (OpenAPI)
- [x] Backward compatibility with static ingestion preserved
- [x] Dynamic ingestion supports source CRUD and run tracking
- [x] MediaWiki config schema exists
- [x] Gateway remains the policy choke point
- [x] No document content or credentials logged/persisted outside intended storage
