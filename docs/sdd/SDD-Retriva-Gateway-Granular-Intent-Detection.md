# SDD Pack — Retriva Gateway Granular Intent Detection

## Status
Proposed

## Scope
Retriva Gateway only.

This SDD adds granular intent detection to Retriva Gateway so that user requests are routed to the correct backend capability instead of always using semantic RAG.

Target architecture:

```text
Retriva WebUI → Retriva Gateway → Retriva Core
```

---

## Motivation

Retriva already stores user-provided metadata in Qdrant payloads, for example:

```json
"user_metadata": {
  "kb_id": "default",
  "project": "apollo",
  "department": "r&d"
}
```

Therefore, the problem is not metadata persistence. The problem is that a query such as:

```text
List all the documents you have dealing with apollo project.
```

is currently handled as a dense semantic RAG query. Dense retrieval is the wrong first step for catalog/listing questions because large documents with many chunks can dominate the candidate pool, while short or image-only documents may be missed even when metadata matches exactly.

The Gateway must distinguish between:

- document catalog queries
- metadata-filtered semantic questions
- pure semantic RAG questions
- artifact generation requests
- ingestion/document-management actions

---

## Design Principles

### DP-1 — Metadata questions are structured queries

Questions asking to list, show, count, or find documents by tag/metadata must be routed to structured document APIs, not vector search.

### DP-2 — Deterministic first

Intent detection must be deterministic for obvious cases. LLM-based intent detection may be added later only as an optional fallback for ambiguous natural language.

### DP-3 — No metadata injection into embeddings

The Gateway must not require user metadata to be injected into embedded chunk text to make metadata queries work.

### DP-4 — Known metadata keys are discovered dynamically

Users may define arbitrary tags at ingestion time. The Gateway must not hardcode a fixed tag schema. It should obtain known metadata keys and values from Core APIs.

---

## Intent Classes

The Gateway must classify user turns into one of the following intents:

```text
catalog_document_list
catalog_document_count
metadata_filtered_rag
pure_rag
artifact_request
ingestion_action
document_management_action
unknown
```

---

## Routing Rules

### catalog_document_list

Examples:

```text
List all documents for project apollo.
Show files tagged department r&d.
Which documents belong to Apollo?
List all documents dealing with apollo project.
```

Routing:

```http
GET /api/v2/documents?metadata.project=apollo
```

No vector search is required.

### catalog_document_count

Examples:

```text
How many documents are tagged project apollo?
Count files for department r&d.
```

Routing:

```http
GET /api/v2/documents/count?metadata.project=apollo
```

### metadata_filtered_rag

Examples:

```text
What are the costs for project apollo?
Summarize the documents tagged department r&d.
What does the Apollo project documentation say about Rust?
```

Routing:

```http
POST /api/v2/retrieval/query
```

with:

```json
{
  "query": "costs",
  "filters": {
    "user_metadata.project": "apollo"
  }
}
```

This uses metadata filters to constrain the candidate set and vector search to rank content inside that set.

### pure_rag

Examples:

```text
What is the maximum power consumption of AURA SOM?
Explain the Cyber Resilience Act obligations.
```

Routing:

```http
POST /api/v2/retrieval/query
```

without metadata filters unless the WebUI explicitly selected filters.

---

## Metadata Extraction

The Gateway must support extraction of metadata filters from user text when the user references known tags.

Examples:

```text
apollo project → user_metadata.project = apollo
project apollo → user_metadata.project = apollo
department r&d → user_metadata.department = r&d
```

The Gateway must use metadata key/value hints from Core:

```http
GET /api/v2/metadata/schema
GET /api/v2/metadata/values?key=project
```

The Gateway must perform case-insensitive matching for keys and values.

---

## WebUI-Provided Filters

Retriva WebUI may explicitly send metadata filters selected by the user.

When explicit WebUI filters are present, they take precedence over natural-language extraction.

Example:

```json
{
  "message": "List documents",
  "filters": {
    "user_metadata.project": "apollo"
  }
}
```

---

## Response Behavior

For catalog/list/count intents, the Gateway should return structured document-level responses, not chunk-level RAG answers.

Example:

```json
{
  "type": "document_list",
  "items": [
    {
      "doc_id": "prj_apollo/costs.png",
      "title": "costs.png",
      "source_path": "prj_apollo/costs.png",
      "user_metadata": {
        "project": "apollo",
        "department": "r&d"
      }
    },
    {
      "doc_id": "prj_apollo/rust-for-beginners.pdf",
      "title": "Rust For Beginners",
      "source_path": "prj_apollo/rust-for-beginners.pdf",
      "user_metadata": {
        "project": "apollo",
        "department": "r&d"
      }
    }
  ]
}
```

The WebUI can render this directly or the Gateway can synthesize a concise assistant response.

---

## API Changes in Gateway

### POST `/gateway/chat`

Must accept optional explicit filters:

```json
{
  "message": "List all documents for project apollo",
  "kb_ids": ["default"],
  "filters": {
    "user_metadata.project": "apollo"
  },
  "stream": false
}
```

Must route according to detected intent.

### GET `/gateway/metadata/schema`

Proxy or normalize Core metadata schema.

### GET `/gateway/metadata/values`

Returns known values for a metadata key.

Example:

```http
GET /gateway/metadata/values?key=project
```

---

## Observability

Gateway must log:

```text
intent_detected
metadata_filters_extracted
catalog_query_routed
metadata_filtered_rag_routed
pure_rag_routed
intent_ambiguous
```

Each log must include correlation ID, intent, extracted filters, selected route, and whether filters came from WebUI or natural language.

---

## Non-Goals

This SDD does not include:

- Changing Qdrant payload structure
- Injecting metadata into embeddings
- Implementing LLM-based intent classification
- Changing Retriva WebUI metadata UI
- Implementing authentication/authorization

---

## Acceptance Criteria

1. Query `List all documents for project apollo` is classified as `catalog_document_list`.
2. Gateway routes catalog document-list queries to Core document metadata APIs, not vector search.
3. Both `costs.png` and `Rust For Beginners` are returned when both have `user_metadata.project=apollo`.
4. Query `What are the costs for project apollo?` is classified as `metadata_filtered_rag`.
5. Metadata-filtered RAG calls Core retrieval with metadata filters.
6. Pure semantic questions still use normal RAG.
7. Explicit WebUI filters override natural-language extraction.
8. Gateway does not require metadata text injection into embeddings.
9. Intent routing decisions are logged with correlation IDs.
10. Unknown or ambiguous intents fall back safely to normal chat or clarification.

---

## One-Sentence Summary

Retriva Gateway gains deterministic granular intent detection so metadata/catalog queries are answered through structured document APIs, while metadata-filtered semantic questions use filtered retrieval and pure semantic questions continue using RAG.
