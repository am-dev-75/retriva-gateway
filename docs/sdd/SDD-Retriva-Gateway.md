
# SDD Pack — Retriva Gateway

## Status
Proposed

## Scope
Retriva Gateway service only.

Retriva Gateway is the server-side Backend-for-Frontend (BFF) used by Retriva WebUI. It sits between the browser application and Retriva Core.

Target architecture:

```text
Retriva WebUI → Retriva Gateway → Retriva Core
```

The Gateway must replace the useful product-level responsibilities previously implemented in the Open WebUI adapter, while removing all Open WebUI-specific workarounds.

---

## Objective

Implement Retriva Gateway as the stable browser-facing control-plane service for Retriva WebUI. The Gateway exposes clean, UI-oriented APIs and translates them into Retriva Core API calls.

The Gateway must support:

- Chat requests
- Knowledge Base management
- Document browsing and deletion
- File and recursive folder ingestion
- User-provided metadata handling
- Ingestion batch/job tracking
- Artifact creation and download
- Runtime configuration
- Future IAM readiness
- Future speech-to-text readiness

Authentication and authorization are out of scope for the first implementation, but the architecture must preserve a clean future path for external IAM integration.

---

## Architectural Role

Retriva Gateway is a control-plane service and Backend-for-Frontend.

Responsibilities:

- Expose browser-friendly APIs
- Normalize frontend requests
- Call Retriva Core APIs
- Hide Retriva Core internal API details from the browser
- Enforce future policy/authorization decisions
- Manage frontend-oriented batch workflows
- Provide stable contracts to Retriva WebUI

Non-responsibilities:

- Vector search implementation
- Embedding generation
- LLM provider calls
- Document parsing
- Artifact rendering
- Long-term storage ownership

Those remain inside Retriva Core.

---

## Design Principles

### DP-1 — Gateway-only browser access

Retriva WebUI MUST call only Retriva Gateway. It MUST NOT call Retriva Core directly.

### DP-2 — Thin but product-aware

The Gateway should be thin in data processing but product-aware in workflow orchestration.

### DP-3 — No Open WebUI compatibility logic

The Gateway MUST NOT carry forward OWUI-specific logic such as:

- OWUI synthetic prompt filtering
- OWUI file polling
- OWUI API key handling
- OWUI payload parsing
- OWUI model proxying

### DP-4 — Structured actions, not directives

The Gateway MUST expose structured APIs so users are not forced to type chat directives.

### DP-5 — IAM-ready

The first implementation ships without authentication, but the request pipeline must be structured so that authentication, user identity, roles, and permissions can be added later.

---

## Technology Assumptions

The SDD does not mandate a framework, but the implementation should use a simple HTTP backend suitable for async file upload and streaming chat.

Recommended choices:

- Python FastAPI, if Retriva Core is Python-based
- Node.js/Fastify, if the frontend ecosystem is preferred

The implementation MUST provide OpenAPI documentation for Gateway endpoints.

---

## Runtime Configuration

Recommended environment variables:

```env
GATEWAY_HOST=0.0.0.0
GATEWAY_PORT=8080
RETRIVA_CORE_BASE_URL=http://retriva-core:8000
RETRIVA_CORE_API_V2_BASE_URL=http://retriva-core:8000/api/v2
GATEWAY_ENABLE_AUTH=false
GATEWAY_ENABLE_ARTIFACTS=true
GATEWAY_ENABLE_FOLDER_UPLOAD=true
GATEWAY_ENABLE_SPEECH_INPUT=false
GATEWAY_MAX_UPLOAD_MB=500
GATEWAY_UPLOAD_TMP_DIR=/tmp/retriva-gateway-uploads
GATEWAY_CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

---

## API Surface

All Gateway endpoints are prefixed with:

```text
/gateway
```

---

## Health and Capabilities

### GET `/gateway/health`

Returns service health.

### GET `/gateway/capabilities`

Returns UI feature availability.

Example response:

```json
{
  "chat": true,
  "knowledge_bases": true,
  "documents": true,
  "ingestion": true,
  "artifacts": true,
  "folder_upload": true,
  "speech_input": false,
  "auth": false
}
```

---

## Chat API

### POST `/gateway/chat`

Handles user chat requests from Retriva WebUI.

Behavior:

- Validate request
- Forward to Retriva Core chat/RAG endpoint
- Stream response if requested
- Preserve source/citation metadata
- Return normalized response to WebUI

The Gateway MUST NOT directly call the LLM provider.

---

## Knowledge Base API

- `GET /gateway/kbs`
- `POST /gateway/kbs`
- `GET /gateway/kbs/{kb_id}`
- `PATCH /gateway/kbs/{kb_id}`
- `DELETE /gateway/kbs/{kb_id}`

Gateway behavior:

- Normalize KB DTOs for the frontend
- Hide Core-specific internal fields
- Preserve future permission hooks

---

## Documents API

- `GET /gateway/documents`
- `GET /gateway/documents/{doc_id}`
- `DELETE /gateway/documents/{doc_id}`

Behavior:

- Map frontend document identifiers to Core document identifiers
- Return normalized status
- Treat idempotent delete as success when Core supports it

---

## Ingestion API

The Gateway must support batch-oriented ingestion suitable for folder upload.

- `POST /gateway/ingestion/batches`
- `POST /gateway/ingestion/batches/{batch_id}/files`
- `GET /gateway/ingestion/batches/{batch_id}`
- `POST /gateway/ingestion/batches/{batch_id}/cancel`
- `POST /gateway/ingestion/jobs/{job_id}/retry`

Behavior:

- Accept file upload from browser
- Preserve relative path
- Merge batch metadata and per-file metadata
- Forward to Retriva Core ingestion API v2
- Track file-level ingestion status

---

## Metadata Handling

The Gateway must accept user-provided metadata from the WebUI as structured JSON.

Metadata must be forwarded to Retriva Core under the expected API v2 metadata structure:

```json
{
  "metadata": {
    "user_metadata": {
      "topic": "cybersecurity",
      "regulation": "CRA"
    }
  }
}
```

The Gateway MUST NOT require chat directives for metadata.

---

## Artifacts API

The Gateway exposes a frontend-friendly proxy to Retriva Core `/api/v2/artifacts`.

- `POST /gateway/artifacts`
- `GET /gateway/artifacts`
- `GET /gateway/artifacts/{artifact_id}`
- `GET /gateway/artifacts/{artifact_id}/content`
- `DELETE /gateway/artifacts/{artifact_id}`

Supported artifact types/formats:

```text
markdown
pdf
document_list
basic_report
docx
xlsx
odt
ods
odp
```

---

## Speech-to-Text Readiness

Speech-to-text is not implemented in the first implementation.

The Gateway must reserve future API compatibility:

```http
POST /gateway/speech/transcriptions
```

Future endpoint. Disabled unless `GATEWAY_ENABLE_SPEECH_INPUT=true`.

When disabled, return `404 Not Found` or `501 Not Implemented`, depending on implementation convention.

---

## Future IAM Readiness

The first implementation has no authentication.

However, Gateway request handling must reserve the concept of a request principal.

Internal request context should include:

```text
principal_id
roles
permissions
```

In the first implementation these may resolve to:

```text
anonymous
[admin]
[*]
```

Future authorization points:

- KB visibility
- document upload
- document deletion
- artifact generation
- settings/admin operations

---

## Error Model

Gateway errors must be normalized for the UI.

Example error response:

```json
{
  "error": {
    "code": "INGESTION_FAILED",
    "message": "The file could not be ingested.",
    "details": {}
  }
}
```

The Gateway MUST NOT expose Core stack traces to the browser.

---

## Observability

Gateway must emit structured logs for:

```text
chat_request_received
chat_request_forwarded
kb_request
file_upload_received
ingestion_batch_created
ingestion_file_forwarded
ingestion_job_status_updated
artifact_request_created
artifact_download_requested
core_request_failed
```

Logs should include correlation IDs.

---

## Non-Goals

This SDD does not include:

- Browser UI implementation
- Retriva Core implementation
- Open WebUI compatibility
- Authentication implementation
- External IAM integration
- Speech-to-text engine implementation
- LLM provider integration in Gateway

---

## Acceptance Criteria

1. Gateway starts and exposes `/gateway/health`.
2. Gateway exposes `/gateway/capabilities`.
3. WebUI can call Gateway without calling Core directly.
4. Chat requests are forwarded to Core and responses are normalized.
5. KB list/create/update/delete calls are available.
6. Documents can be listed, inspected, and deleted.
7. Ingestion batches can be created.
8. Files can be uploaded to a batch.
9. Relative folder paths are preserved.
10. User metadata is forwarded as structured metadata.
11. Batch/job status can be retrieved.
12. Artifacts can be created, listed, downloaded, and deleted.
13. STT endpoint is disabled by default but reserved.
14. No authentication is required in the first implementation.
15. Request context is IAM-ready.
16. Core errors are normalized before reaching WebUI.
17. Gateway emits structured logs with correlation IDs.
18. OpenAPI documentation is available.

---

## One-Sentence Summary

Retriva Gateway is the BFF between Retriva WebUI and Retriva Core, exposing clean UI-oriented APIs for chat, KBs, documents, ingestion, metadata, artifacts, and future STT/IAM while hiding Core internals from the browser.
