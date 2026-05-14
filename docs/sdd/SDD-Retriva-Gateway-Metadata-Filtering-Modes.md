# SDD Pack — Retriva Gateway Metadata Filtering Modes

## Status
Proposed

## Scope
Retriva Gateway only.

This SDD modifies Retriva Gateway to support explicit metadata filtering modes sent by Retriva WebUI.

Target architecture:

```text
Retriva WebUI → Retriva Gateway → Retriva Core
```

---

## Objective

Implement Gateway support for explicit metadata filtering modes:

```text
soft = Use as ranking hints
hard = Require matching metadata
```

The Gateway must stop relying on natural-language intent detection to decide whether metadata is strict or soft. The WebUI provides the mode explicitly.

---

## Routing Model

### Documents/Search screen flow

WebUI calls:

```http
POST /gateway/documents/search
```

Gateway forwards to Core document discovery:

```http
POST /api/v2/documents/search
```

The response is document-level.

### Chat screen flow

WebUI calls:

```http
POST /gateway/chat
```

Gateway forwards to Core RAG retrieval/answer generation with the provided metadata mode.

The response is an answer, not a document catalog result.

---

## API Contract

### Common metadata filter object

Gateway must accept:

```json
{
  "field": "user_metadata.project",
  "operator": "eq",
  "value": "apollo"
}
```

Required operators:

```text
eq
exists
```

Optional future operators:

```text
neq
contains
in
```

### Metadata filter mode

Allowed values:

```text
soft
hard
```

Meaning:

```text
soft → metadata is ranking/recall signal
hard → metadata is mandatory payload constraint
```

---

## Gateway Endpoints

### POST `/gateway/chat`

Request:

```json
{
  "message": "What are the costs of the Apollo project?",
  "kb_ids": ["default"],
  "metadata_filters": [
    {
      "field": "user_metadata.project",
      "operator": "eq",
      "value": "apollo"
    }
  ],
  "metadata_filter_mode": "soft",
  "stream": true
}
```

Gateway behavior:

- Validate `metadata_filter_mode`.
- Validate metadata filter fields and operators.
- Normalize filter fields if needed.
- Forward to Core retrieval/answer-generation endpoint.
- Do not reinterpret the metadata mode from natural language.

---

### POST `/gateway/documents/search`

Request:

```json
{
  "query": "apollo project",
  "kb_ids": ["default"],
  "metadata_filters": [
    {
      "field": "user_metadata.project",
      "operator": "eq",
      "value": "apollo"
    }
  ],
  "metadata_filter_mode": "soft",
  "limit": 50
}
```

Gateway behavior:

- Forward to Core `/api/v2/documents/search`.
- Return document-level results.
- Do not call chat/RAG path.

---

### GET `/gateway/metadata/schema`

Proxy/normalize Core metadata schema.

### GET `/gateway/metadata/values?field=<field>`

Proxy/normalize known values for a metadata field.

---

## Field Normalization

Gateway should allow field names exposed by Core schema.

Examples:

```text
user_metadata.project
chunk_type
language
source_path
page_title
doc_id
```

Gateway must not restrict filtering only to `user_metadata`.

---

## Behavior Rules

### Rule 1 — No hard/soft inference

Gateway must not infer hard vs soft metadata behavior from user query wording.

### Rule 2 — WebUI mode is authoritative

If WebUI sends `metadata_filter_mode=hard`, Gateway forwards hard mode.

If WebUI sends `metadata_filter_mode=soft`, Gateway forwards soft mode.

### Rule 3 — Default mode

If mode is omitted, Gateway should default to:

```text
soft
```

### Rule 4 — Invalid fields/operators

Invalid fields or operators should return a normalized 400 error.

---

## Observability

Gateway must log:

```text
metadata_mode_received
metadata_filters_validated
document_search_forwarded
chat_with_metadata_mode_forwarded
metadata_filter_validation_failed
```

Each log must include:

- correlation_id
- endpoint
- metadata_filter_mode
- metadata filter count
- destination Core endpoint

---

## Non-Goals

This SDD does not include:

- Natural-language hard-vs-soft intent detection
- LLM-based intent detection
- Retriva WebUI changes
- Retriva Core implementation
- Metadata injection into embeddings
- Authentication/authorization

---

## Acceptance Criteria

1. `/gateway/chat` accepts `metadata_filters` and `metadata_filter_mode`.
2. `/gateway/documents/search` accepts `metadata_filters` and `metadata_filter_mode`.
3. Gateway forwards `soft` mode unchanged to Core.
4. Gateway forwards `hard` mode unchanged to Core.
5. Gateway defaults missing mode to `soft`.
6. Gateway validates metadata filter field/operator syntax.
7. Gateway supports fields beyond `user_metadata`, including `chunk_type` and `language` when exposed by Core schema.
8. Documents/Search requests are routed to Core document discovery, not chat.
9. Chat requests are routed to Core RAG answer generation, not document discovery.
10. Gateway logs metadata mode and filters with correlation IDs.

---

## One-Sentence Summary

Retriva Gateway receives explicit metadata filtering mode from WebUI and routes document search and chat requests without guessing user intent from natural language.
