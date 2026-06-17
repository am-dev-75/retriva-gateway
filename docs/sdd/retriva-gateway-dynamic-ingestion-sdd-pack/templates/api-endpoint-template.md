# API Endpoint Template

## Endpoint

```http
METHOD /gateway/path
```

## Purpose

## Authorization

## Request

```json
{}
```

## Response

```json
{}
```

## Errors

- `400` invalid request
- `401` unauthenticated
- `403` unauthorized
- `404` not found
- `409` invalid lifecycle transition
- `500` internal error without content leakage

## Logging

Allowed fields only:

- request_id
- tenant_id
- source_id
- operation
- status
- latency_ms
