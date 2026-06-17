# /architect — Dynamic Ingestion Gateway Architecture Plan

You are working in the Retriva Gateway repository.

## Purpose

Convert the approved spec into an implementation architecture and task plan.

## Inputs

- `specs/dynamic-ingestion-gateway/spec.md`
- `memory/constitution.md`
- Existing Gateway source tree

## Instructions

1. Inspect existing code paths for ingestion, documents, KBs, Gateway routes, Core client, auth, and persistence.
2. Produce `artifacts/dynamic-ingestion/recon.md` summarizing current architecture.
3. Update `specs/dynamic-ingestion-gateway/plan.md` with concrete files/modules to modify.
4. Include a database/persistence migration plan if the project uses a DB.
5. Include compatibility plan for static ingestion.
6. Include test plan mapped to implementation tasks.
7. Do not edit production code except docs/spec artifacts.

## Required output

- `artifacts/dynamic-ingestion/recon.md`
- Updated `specs/dynamic-ingestion-gateway/plan.md`
- `artifacts/dynamic-ingestion/task-graph.md`
