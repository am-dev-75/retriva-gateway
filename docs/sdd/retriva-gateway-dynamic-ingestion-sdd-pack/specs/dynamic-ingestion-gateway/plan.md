# Architecture Plan — Dynamic Ingestion Support in Retriva Gateway

## Phase 0 — Codebase reconnaissance

Agent must inspect the existing Gateway repository before editing:

- Framework used, e.g. FastAPI/Flask/etc.
- Existing route registration pattern.
- Existing models/schemas.
- Existing persistence layer.
- Existing auth middleware.
- Existing Core client.
- Existing ingestion orchestration services.
- Existing test style.

Produce `artifacts/dynamic-ingestion/recon.md` before implementation.

## Phase 1 — Domain model and schemas

Add models/schemas for:

- `SourceInstance`
- `SourceCheckpoint`
- `SourceRun`
- `SourceItemState`
- `SourceStatus`
- `ConnectorType`
- `MediaWikiSourceConfig`
- `CreateSourceRequest`
- `UpdateSourceRequest`
- `SourceResponse`
- `SourceRunResponse`

## Phase 2 — Persistence abstraction

Add a repository abstraction, even if backed initially by JSON/SQLite/current Gateway storage:

- `SourceRepository`
- `SourceRunRepository`
- `SourceCheckpointRepository`
- `SourceItemStateRepository`

Required methods:

- create/get/list/update/delete source
- create/update/list runs
- get/save checkpoint
- upsert/list item states

## Phase 3 — Public Gateway API

Implement endpoints:

```http
POST   /gateway/sources
GET    /gateway/sources
GET    /gateway/sources/{source_id}
PATCH  /gateway/sources/{source_id}
DELETE /gateway/sources/{source_id}
POST   /gateway/sources/{source_id}/sync
POST   /gateway/sources/{source_id}/pause
POST   /gateway/sources/{source_id}/resume
GET    /gateway/sources/{source_id}/status
GET    /gateway/sources/{source_id}/runs
GET    /gateway/sources/{source_id}/runs/{run_id}
```

## Phase 4 — Connector Manager skeleton

Add:

- `ConnectorManager`
- `ConnectorRegistry`
- `ConnectorWorkerClient` or job dispatcher abstraction
- `MediaWikiConnectorDescriptor`

For now, manual sync may enqueue a run in persistence without launching a real worker if the worker is external.

## Phase 5 — Internal worker API

Implement service-authenticated internal endpoints for:

- run heartbeat
- run event updates
- run completion
- checkpoint updates
- source item state updates
- ingestion session issuance

## Phase 6 — Core ingestion integration contract

Do not implement a parallel ingestion pipeline in Gateway.

Add a Gateway service that produces either:

1. a normal Gateway ingestion batch using existing Gateway ingestion APIs, or
2. a short-lived ingestion session for connector-to-Core upload.

Document the selected approach in `docs/dynamic-ingestion-core-contract.md`.

## Phase 7 — Tests

Add tests for:

- source CRUD
- MediaWiki config validation
- invalid connector type rejection
- pause/resume transitions
- manual sync run creation
- first-sync lifecycle transitions
- no inline secret persistence
- no content in logs where testable
- internal endpoint authentication

## Phase 8 — Artifacts

Generate:

- OpenAPI update or route documentation.
- State machine diagram.
- Example request/response JSON.
- Verification checklist.
