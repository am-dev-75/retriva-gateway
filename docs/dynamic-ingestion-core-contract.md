# Dynamic Ingestion — Core Integration Contract

## Selected approach

**Approach A — Connector calls Gateway** (from the SDD pack reference: `connector → Gateway → Core`)

Gateway remains the single policy and audit choke point for all ingestion.

### Rationale

- Gateway already implements ingestion batch management (`POST /gateway/ingestion/batches`).
- The existing `CoreClient` provides the `httpx.AsyncClient` infrastructure to forward requests to Core.
- Approach A requires no changes to Core's ingestion API.
- Approach B (short-lived scoped tokens) is reserved for future high-throughput connectors.

## How it works

```text
connector_worker → Gateway internal API → Gateway ingestion service → Core ingestion API
```

1. Connector worker calls `POST /gateway/internal/sources/{id}/ingestion-session` to get:
   - `kb_id`, `tenant_id`, `source_id`, optional `run_id`
   - `batch_metadata` (includes `source_type`, `source_id`, optionally `run_id`)

2. Connector worker uses the returned metadata to construct document payloads matching the normalized schema.

3. Connector worker submits documents through Gateway's existing ingestion batch API or directly via Core (future Approach B).

4. Connector worker reports item-level status back via `POST /internal/sources/{id}/runs/{run_id}/events`.

## Normalized document payload

Per the SDD pack contract, each document submitted for dynamic ingestion must include:

```json
{
  "tenant_id": "internal-company",
  "kb_id": "rd_mediawiki",
  "source_type": "mediawiki",
  "source_id": "src_...",
  "source_item_id": "mediawiki:rdwiki:page:12345",
  "source_revision": "987654",
  "document_title": "Hydraulic Test Procedure",
  "content_type": "text/html",
  "content_ref_or_content": "...",
  "metadata": {
    "source_system": "mediawiki",
    "namespace": 100,
    "source_url": "https://mediawiki.company.local/wiki/...",
    "categories": ["R&D", "Procedures"]
  }
}
```

## Forbidden operations in Gateway

Gateway must **not** implement:

- Chunking
- Embedding
- Qdrant upsert
- Retrieval-index manipulation

All of these remain Core's responsibility.
