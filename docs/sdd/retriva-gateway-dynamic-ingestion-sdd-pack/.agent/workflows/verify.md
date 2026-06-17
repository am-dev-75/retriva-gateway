# /verify — Dynamic Ingestion Gateway Verification

You are working in the Retriva Gateway repository.

## Purpose

Verify the implementation against the spec, constitution, and acceptance criteria.

## Inputs

- `specs/dynamic-ingestion-gateway/spec.md`
- `specs/dynamic-ingestion-gateway/plan.md`
- `specs/dynamic-ingestion-gateway/verification.md`
- Current code changes

## Instructions

1. Run project-native tests.
2. Run project-native lint/type checks if available.
3. Inspect changed files for accidental content/secret logging.
4. Verify static ingestion routes still exist and are unchanged unless explicitly needed.
5. Verify every new persistent record includes `tenant_id` where applicable.
6. Verify source credentials are represented by `secret_ref`, not inline secrets.
7. Generate a verification report.
8. If failures occur, fix them or document blockers clearly.

## Required output

- Passing tests or documented blockers
- `artifacts/dynamic-ingestion/verification-report.md`
- `artifacts/dynamic-ingestion/security-review.md`
