# /define — Dynamic Ingestion Gateway Feature Definition

You are working in the Retriva Gateway repository.

## Purpose

Transform the provided feature brief into a rigorous SDD specification for adding dynamic ingestion support to Gateway.

## Inputs

- `specs/dynamic-ingestion-gateway/feature-brief.md`
- `memory/constitution.md`
- Existing Gateway codebase
- Existing README/OpenAPI/docs if present

## Instructions

1. Inspect the repository structure.
2. Identify the web framework, route style, schema style, persistence pattern, auth pattern, and test style.
3. Read the feature brief and constitution.
4. Generate or update `specs/dynamic-ingestion-gateway/spec.md`.
5. The spec must define:
   - user stories,
   - source lifecycle,
   - API endpoints,
   - data model,
   - security requirements,
   - first-sync baseline/catch-up rule,
   - non-goals,
   - acceptance criteria.
6. Do not edit production code in this phase.
7. Emit an artifact: `artifacts/dynamic-ingestion/definition-review.md`.

## Required output

- Updated `specs/dynamic-ingestion-gateway/spec.md`
- `artifacts/dynamic-ingestion/definition-review.md`
