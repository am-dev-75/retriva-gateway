# Codebase Reconnaissance — Dynamic Ingestion

## Summary

Reconnaissance performed prior to dynamic ingestion implementation.
All findings documented below were used to guide implementation decisions.

## Findings

| Concern | Pattern Found | Source |
|---|---|---|
| **Framework** | FastAPI (Starlette) | `main.py`, `pyproject.toml` |
| **Route registration** | Centralized in `api/router.py` with `api_router` (`/gateway`) and `api_v2_router` (`/api/v2`) prefixes | `api/router.py` |
| **Models / schemas** | Pydantic models in `core/models.py` | `core/models.py` |
| **Persistence** | In-memory dicts for ingestion batches (no DB) | `api/v2/ingestion.py:L30` |
| **Auth middleware** | `GATEWAY_ENABLE_AUTH=false`; no auth middleware deployed | `config.py` |
| **HTTP client** | `httpx.AsyncClient` via `CoreClient` | `core/client.py` |
| **Core URLs** | Separate ingestion (`RETRIVA_CORE_INGESTION_URL`) and chat (`RETRIVA_CORE_CHAT_URL`) | `config.py` |
| **Configuration** | pydantic-settings `BaseSettings`, `.env` loaded via `SettingsConfigDict` | `config.py` |
| **Logging** | `loguru` — no content logging | `main.py`, all modules |
| **Testing** | `unittest.TestCase` + `fastapi.testclient.TestClient` + `unittest.mock.patch` | `tests/` |
| **Existing ingestion** | Batch-oriented: `BatchCreateRequest` → file upload → Core forwarding | `api/v2/ingestion.py` |

## Design Decisions Informed by Recon

1. **Storage**: JSON file-backed repository (matching existing in-memory pattern, adds durability).
2. **Routing**: New routers registered in existing `api/router.py`.
3. **Auth**: Feature-flagged `X-Service-Token` for internal endpoints.
4. **Models**: Separate `core/source_models.py` to avoid disturbing existing `core/models.py`.
5. **Tests**: Follow existing `unittest` + `TestClient` pattern.
