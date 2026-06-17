# Dynamic Ingestion Core Contract

Dynamic ingestion must use Core's canonical ingestion pipeline.

Gateway may implement one of two approaches:

## Approach A — Connector calls Gateway

```text
connector -> Gateway -> Core
```

Recommended for first implementation because Gateway remains the single policy and audit choke point.

## Approach B — Gateway-issued ingestion session

```text
connector -> Gateway: request ingestion session
Gateway -> connector: short-lived scoped token
connector -> Core: upload document with token
Core -> Gateway: status / or connector reports status
```

Recommended later for high-throughput connectors.

## Required normalized document payload

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

## Forbidden

Gateway must not implement its own chunking, embedding, Qdrant upsert, or retrieval-index manipulation.
