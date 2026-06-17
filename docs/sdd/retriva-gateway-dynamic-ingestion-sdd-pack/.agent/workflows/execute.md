# /execute — Dynamic Ingestion Gateway Implementation

You are working in the Retriva Gateway repository.

## Purpose

Implement the architecture plan for dynamic ingestion support.

## Inputs

- `specs/dynamic-ingestion-gateway/spec.md`
- `specs/dynamic-ingestion-gateway/plan.md`
- `memory/constitution.md`
- Existing Gateway codebase

## Instructions

1. Follow the existing repository conventions.
2. Implement the smallest coherent vertical slice first:
   - models/schemas,
   - repository abstraction,
   - source CRUD endpoints,
   - run tracking,
   - pause/resume/manual sync.
3. Add MediaWiki config validation.
4. Add internal connector worker API only if the repo structure can support it cleanly.
5. Do not implement a full MediaWiki network client unless it belongs in this repository.
6. Preserve existing static ingestion behavior.
7. Add tests with repository-native framework.
8. Ensure logs never include content or secrets.
9. Emit implementation notes.

## Required output

- Code changes
- Tests
- Updated API docs/OpenAPI if present
- `artifacts/dynamic-ingestion/implementation-notes.md`
