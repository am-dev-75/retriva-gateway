# Feature Brief — Dynamic Ingestion Support in Retriva Gateway

## Goal

Add dynamic ingestion support to Retriva Gateway so users can configure **Connected Sources** that keep a Retriva Knowledge Base synchronized with external systems.

The first target source type is **MediaWiki**. Future source types include SharePoint, OneDrive, Google Drive, SFTP folders, and other enterprise repositories.

## Current state

Retriva currently supports static ingestion:

```text
User selects files/folders
  -> WebUI uploads them
  -> Gateway creates ingestion batch
  -> Core ingests documents
```

## Desired state

Retriva supports both static and dynamic ingestion:

```text
Static ingestion:
User uploads files/folders once.

Dynamic ingestion:
User creates a Connected Source.
Gateway validates and stores source config.
Connector Manager schedules source sync runs.
Connector detects changes and submits normalized documents into Core ingestion.
Gateway exposes status/run/error APIs to WebUI.
```

## First implementation scope

Implement Gateway-side support only:

- Source CRUD APIs.
- Source lifecycle/status model.
- Sync run tracking.
- Connector Manager abstraction.
- MediaWiki source configuration schema.
- Manual sync trigger endpoint.
- Pause/resume endpoint.
- Baseline/catch-up/incremental state machine representation.
- Internal interface for connector workers.
- Tests.

The actual MediaWiki connector can be mocked or represented as an interface if not part of the Gateway repository.

## User-facing terminology

Use **Connected Sources** in UI/API documentation. Internally, the domain may use `dynamic_source` or `source_instance`.

## Key source lifecycle

```text
CREATED
VALIDATING_CONNECTION
BASELINE_PENDING
BASELINE_RUNNING
CATCHUP_RUNNING
ACTIVE
PAUSED
DEGRADED
FAILED
DELETING
DELETED
```

## Critical first-sync rule

A source must not switch to incremental mode until it has completed:

1. baseline start watermark capture,
2. full baseline inventory/ingestion,
3. catch-up delta from baseline start,
4. checkpoint save.

## Acceptance criteria

- WebUI can call Gateway to create/list/read/update/delete Connected Sources.
- A MediaWiki source config validates required fields.
- Gateway persists source status, checkpoint metadata, run summaries, and source item mapping metadata.
- Manual sync trigger creates a sync run.
- Pause/resume works at source level.
- Gateway never logs content/credentials.
- Connector worker contract is documented and tested.
- Unit/integration tests cover lifecycle and first-sync state transitions.
