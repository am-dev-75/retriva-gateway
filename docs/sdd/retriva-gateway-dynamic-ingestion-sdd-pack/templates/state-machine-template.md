# Source State Machine Template

```text
CREATED
  -> VALIDATING_CONNECTION
  -> BASELINE_PENDING
  -> BASELINE_RUNNING
  -> CATCHUP_RUNNING
  -> ACTIVE

ACTIVE -> PAUSED
PAUSED -> ACTIVE
ACTIVE -> DEGRADED
DEGRADED -> ACTIVE
ANY -> FAILED
ANY -> DELETING -> DELETED
```

## Transition rules

- `BASELINE_RUNNING` cannot move directly to `ACTIVE`; it must pass through `CATCHUP_RUNNING`.
- `ACTIVE` requires checkpoint saved.
- `FAILED` requires error code.
- `DELETING` requires deletion policy.
