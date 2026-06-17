# Dynamic Ingestion — State Machine

## Source status transitions

```text
                              ┌──────────────────────────┐
                              │                          │
    ┌─────────────────────────┴───────┐                  │
    │                                 │                  │
    │         BASELINE_PENDING        │ ◄── POST /sources (create)
    │                                 │
    └──────┬──────────────┬───────────┘
           │              │
     POST /sync      POST /pause
           │              │
           ▼              ▼
    ┌──────────────┐  ┌─────────┐
    │  BASELINE    │  │         │
    │  _RUNNING    │  │  PAUSED │ ◄── from any pausable state
    │              │  │         │
    └──────┬───┬───┘  └────┬────┘
           │   │           │
    complete│  fail    POST /resume
           │   │           │
           ▼   │     ┌─────┘
    ┌──────────┐│    ▼ (restores previous state)
    │ CATCHUP  ││
    │ _RUNNING ││
    └──────┬─┬─┘│
           │ │  │
    complete│ │  │
           │ │  │
           ▼ │  │
    ┌────────┐│  │
    │ ACTIVE ││  │
    └──┬─────┘│  │
       │      │  │
       │      ▼  ▼
       │   ┌────────┐
       │   │ FAILED │
       │   └────────┘
       │
  DELETE
       │
       ▼
    ┌──────────┐     ┌─────────┐
    │ DELETING │ ──► │ DELETED │
    └──────────┘     └─────────┘
```

## Sync mode transitions

```text
    baseline ──(baseline run completes)──► catchup ──(catchup run completes)──► incremental
```

## Pausable states

- `ACTIVE`
- `BASELINE_PENDING`
- `BASELINE_RUNNING`
- `CATCHUP_RUNNING`
- `DEGRADED`
