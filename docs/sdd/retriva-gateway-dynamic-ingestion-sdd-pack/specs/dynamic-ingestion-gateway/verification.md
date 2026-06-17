# Verification Plan — Dynamic Ingestion Support in Retriva Gateway

## Static checks

Run the repository's existing formatters, linters, and type checks. If unknown, inspect project config and choose the project-native commands.

Expected examples:

```bash
python -m pytest
python -m ruff check .
python -m mypy .
```

Only run commands that exist in the repository.

## Unit tests

Required test coverage:

1. Create MediaWiki source.
2. Reject unsupported connector type.
3. Reject invalid MediaWiki API URL.
4. Store `secret_ref`, never raw secret.
5. List sources by tenant.
6. Get source status.
7. Pause active/pending source.
8. Resume paused source.
9. Manual sync creates a `SourceRun`.
10. First-sync lifecycle moves through baseline and catch-up states.
11. Incremental checkpoint is saved only after catch-up completion.
12. Internal endpoints require service authentication.

## Integration tests with mocked Core

Use a fake Core client to verify that Gateway dynamic ingestion does not bypass the existing ingestion flow.

Scenarios:

- source run requests ingestion session;
- document event maps to ingestion request;
- Gateway records returned `doc_id` in source item state;
- duplicate `source_item_id + source_revision + content_hash` is idempotent.

## Security verification

Verify:

- no content fields are logged by source APIs;
- source config response redacts secret fields;
- credentials never appear in persisted source record;
- unauthorized user cannot create/delete/pause/resume source;
- user cannot set arbitrary connector image/command;
- user cannot configure arbitrary forbidden host if allowlist exists.

## Manual smoke test

```bash
# Create source
curl -X POST http://localhost:8000/gateway/sources \
  -H 'Content-Type: application/json' \
  -d @artifacts/examples/create-mediawiki-source.json

# List sources
curl http://localhost:8000/gateway/sources

# Trigger manual sync
curl -X POST http://localhost:8000/gateway/sources/src_example/sync

# Check runs
curl http://localhost:8000/gateway/sources/src_example/runs
```

## Definition of done

- All tests pass.
- API docs updated.
- Backward compatibility with static ingestion preserved.
- Dynamic ingestion supports source CRUD and run tracking.
- MediaWiki config schema exists.
- Gateway remains the policy choke point.
- No document content or credentials logged/persisted outside intended storage.
