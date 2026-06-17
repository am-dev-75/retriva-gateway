# Retriva Gateway Dynamic Ingestion Constitution

## Mission

Extend Retriva Gateway so it becomes the control-plane authority for **dynamic ingestion sources** while preserving Retriva's core separation of concerns:

- WebUI configures and observes ingestion.
- Gateway authorizes, validates, orchestrates, and reports.
- Connectors adapt external sources.
- Core performs canonical ingestion, metadata handling, chunking, embeddings, and indexing.

## Non-negotiable principles

### 1. Gateway remains the policy choke point

All source creation, update, pause, resume, delete, and manual sync operations must pass through Gateway APIs.

### 2. Connectors must not bypass policy

Connectors must not be exposed to WebUI directly. A connector may call Gateway or use a short-lived ingestion session granted by Gateway. Direct connector-to-Core ingestion is allowed only through a signed, scoped, short-lived internal token issued by Gateway.

### 3. Core remains the canonical ingestion pipeline

Static and dynamic ingestion must converge before or at Core. Dynamic ingestion must not implement its own chunking, embedding, vector upsert, or document catalog semantics inside Gateway.

### 4. No sensitive content in logs

Gateway and connector-manager logs must never include:

- document content,
- MediaWiki page body,
- retrieved chunks,
- prompts,
- answers,
- embedding vectors,
- raw exception messages containing content,
- credentials.

### 5. Secrets are referenced, not stored inline

Source credentials must be stored in a dedicated secret backend or environment-specific secret store. Gateway persistence stores only `secret_ref` values.

### 6. Dynamic ingestion must be resumable

Initial baseline scans, catch-up deltas, and incremental syncs must support idempotent retry and crash recovery.

### 7. First sync must not miss changes

Initial sync must use:

1. baseline start watermark,
2. full baseline scan,
3. catch-up delta from baseline start,
4. activation only after catch-up completion.

### 8. Deletion semantics must be explicit

Source deletion and remote document deletion must support soft-delete semantics first. Hard deletion requires explicit policy.

### 9. Tenant boundary from day one

Even in milestone #1, all new persistent records must include `tenant_id`, with `internal-company` as the initial value.

### 10. Future connectors must fit the same contract

MediaWiki is the first connector, not a special case. The model must also support SharePoint, OneDrive, Google Drive, SFTP, and future enterprise repositories.
