# SDD Specification — Dynamic Ingestion Support in Retriva Gateway

## 1. Overview

Retriva Gateway shall be extended to manage dynamic ingestion sources, called **Connected Sources**, whose external content is periodically synchronized into a Retriva Knowledge Base through the existing Core ingestion pipeline.

The first connector type is MediaWiki. The design must support future connector types without changing the public API shape radically.

## 2. Actors

- `end_user`: views source status and may trigger syncs if authorized.
- `admin_user`: creates, updates, pauses, resumes, and deletes sources.
- `retriva_webui`: calls Gateway APIs.
- `retriva_gateway`: validates, persists, authorizes, and orchestrates dynamic ingestion.
- `connector_manager`: schedules and launches connector work.
- `connector_worker`: source-specific adapter, e.g. MediaWiki.
- `retriva_core`: canonical ingestion system.
- `secret_store`: stores source credentials.

## 3. Domain model

### 3.1 SourceInstance

Required fields:

```json
{
  "source_id": "src_...",
  "tenant_id": "internal-company",
  "connector_type": "mediawiki",
  "display_name": "R&D MediaWiki",
  "target_kb_id": "rd_mediawiki",
  "status": "BASELINE_PENDING",
  "sync_mode": "baseline",
  "schedule": "*/15 * * * *",
  "config": {},
  "secret_ref": "secret://...",
  "created_by": "user_hash",
  "created_at": "...",
  "updated_at": "..."
}
```

### 3.2 SourceCheckpoint

```json
{
  "source_id": "src_...",
  "checkpoint_type": "mediawiki_recentchanges",
  "baseline_started_at": "...",
  "last_seen_timestamp": "...",
  "last_seen_rcid": 123456,
  "cursor": {},
  "updated_at": "..."
}
```

### 3.3 SourceRun

```json
{
  "run_id": "run_...",
  "source_id": "src_...",
  "tenant_id": "internal-company",
  "phase": "baseline_scan",
  "status": "running",
  "started_at": "...",
  "finished_at": null,
  "processed_items": 0,
  "failed_items": 0,
  "skipped_items": 0,
  "error_code": null
}
```

### 3.4 SourceItemState

```json
{
  "source_id": "src_...",
  "source_item_id": "mediawiki:rdwiki:page:12345",
  "source_revision": "987654",
  "retriva_doc_id": "doc_...",
  "content_hash": "sha256:...",
  "status": "indexed",
  "last_synced_at": "..."
}
```

## 4. API requirements

### 4.1 Public Gateway API for WebUI

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
GET    /gateway/sources/{source_id}/items
```

### 4.2 Internal API for connector workers

```http
POST /gateway/internal/sources/{source_id}/runs/{run_id}/heartbeat
POST /gateway/internal/sources/{source_id}/runs/{run_id}/events
POST /gateway/internal/sources/{source_id}/runs/{run_id}/complete
POST /gateway/internal/sources/{source_id}/ingestion-session
```

The ingestion session response must be scoped to one source, one tenant, and optionally one run.

## 5. MediaWiki connector config schema

```json
{
  "api_url": "https://mediawiki.company.local/api.php",
  "auth_mode": "bot_password|oauth|none",
  "allowed_namespaces": [0, 100, 102],
  "include_categories": ["R&D", "Procedures"],
  "exclude_categories": ["Obsolete"],
  "page_title_prefix": null,
  "sync_interval_minutes": 15,
  "delete_policy": "soft_delete",
  "availability_policy": "hide_until_initial_sync_complete"
}
```

## 6. First-sync state machine

```text
BASELINE_PENDING
  -> BASELINE_RUNNING
  -> CATCHUP_RUNNING
  -> ACTIVE
```

Gateway must persist enough state for a worker to resume after crash.

## 7. Security requirements

- Store credentials only through `secret_ref`.
- Do not log source credentials or document content.
- Source URLs must be validated and optionally allowlisted.
- Connector type must be allowlisted.
- Only authorized roles can create/delete/pause/resume sources.
- Internal endpoints require service authentication.
- Each persistent record must include `tenant_id`.

## 8. Non-functional requirements

- Idempotent source creation by client-provided idempotency key.
- Idempotent ingestion event processing using `source_item_id + source_revision + content_hash`.
- Pagination on list endpoints.
- Content-free status and telemetry.
- Backward compatibility with static ingestion.

## 9. Out of scope

- Full MediaWiki client implementation unless Gateway repository already owns connector code.
- SharePoint/Google Drive/SFTP implementations.
- Per-document permission-aware retrieval.
- UI implementation beyond OpenAPI/API support.
