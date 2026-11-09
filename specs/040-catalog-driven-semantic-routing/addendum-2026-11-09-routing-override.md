# Addendum — user-facing routing override (2026-11-09)

Status: implemented (owner-selected WebUI-level remediation)
Scope: WebUI chat header switch + additive Gateway chat-request field
Governing specs: Spec 040 (catalog-driven semantic routing), Spec 001
(deterministic safety layer), ADR-045

## Context

The 2026-11-08 incident asked, in Italian, why a staged import-batch row
was `AMBIGUOUS_MATCH` instead of `CREATE_ORGANIZATION`. The deterministic
`R-QUOTED` veto classified the turn as a quoted example (`RAG_QUESTION`),
the semantic router was out of band, and the RAG plane — which holds no
campaign staging data and no import-disposition documentation — returned
the grounding refusal. The relational facts existed in the CRM plane.

The owner chose a user-facing control instead of the earlier remediation
package: a per-session switch that forces the turn onto the Company
Intelligence (deterministic-hemisphere) plane.

## Decision

The override changes **plane selection only**. It never loosens, bypasses,
or reinterprets the deterministic safety layer:

1. `force_deterministic` is an additive optional chat-request boolean,
   default `false`. Absent/false keeps the request body and behavior
   byte-identical to the current system (no new vocabulary, no new
   routing path).
2. When true, the deterministic pipeline runs **first and unchanged**.
   Its terminal `CLARIFY` outcomes (guards, vetoes, unresolved
   resources, ambiguous workflow turns) are returned verbatim.
3. Consequential command outcomes (`AGENT_LOOP` with
   `consequential_operations`, or a claimed/resolved confirmation
   context) keep the established command/confirmation semantics. The
   override never downgrades them to read-only and never executes them.
4. All remaining turns (informational RAG, non-adjacent ambiguity, safe
   workflow) enter the agent loop with the read-only admission subset
   (`destructive=False`), exactly matching semantic `FAMILY` routing.
   A destructive tool call is rejected at execution time
   (`tool_not_allowed`), and the registry is filtered pre-loop.
5. The override is non-streaming only. Streaming keeps the existing
   Spec 001 streaming policy; a forced streaming request falls through
   unchanged.
6. The UI switch is per-session state, default off, not persisted; a
   page reload starts a fresh session with the switch off.

## Mode / flag matrix

| `AGENT_INTENT_ROUTER_MODE` | flag absent/false | flag true |
| --- | --- | --- |
| `off` | legacy router (rollback contract, unchanged) | deterministic safety first; terminal outcomes kept; non-terminal turns forced to the read-only agent loop |
| `shadow` | deterministic pipeline; shadow semantic records; served route unchanged | deterministic safety first; no classifier/semantic call; non-terminal turns forced to the read-only agent loop |
| `active` | deterministic pipeline + semantic router (current behavior) | deterministic safety first; no classifier/semantic call; non-terminal turns forced to the read-only agent loop |

In every mode the flag is an explicit per-turn opt-in; the default path
is unchanged.

## Observability

A content-free counter records the served override decision:

```
routing_decision_total{route="AGENT_LOOP"|"CLARIFY", source="forced_override"}
```

The underlying deterministic evaluation also records its own
`source="deterministic"` decision for the same turn (the safety-layer
view). Logs carry only categorical fields (`served_route`,
`safety_route`, `intent`, `reason_codes`, correlation id) — never message
text, tool arguments, or model output.

## D-4 freeze

No deterministic recall vocabulary was added or changed:
`deterministic.py`, `core/intent.py`, and `taxonomy.py` are untouched.
The override is a routing seam at the chat boundary. The known
pre-existing vocabulary gaps (`batches?` does not match singular
"batch"; the real `ibth_` batch prefix is absent from the identifier
map) remain in place and are out of scope. Any change to them requires an
explicit owner-approved Spec 001/040 revision, not a drive-by edit.

## Residual notes

- The campaign-history row view (`_campaign_row_view`) still does not
  expose `selected_disposition` and labels a single-candidate
  review-required row as `unmatched`; the imports review surface exposes
  the persisted `AMBIGUOUS_MATCH`. This is a known data-contract gap,
  not fixed by this addendum.
- The RAG plane still contains no import-disposition documentation.
  Ingesting curated product documentation remains a separate owner
  decision; campaign/import data stays out of the knowledge base.
- The switch has no server-side persistence by design; multi-tab or
  reload behavior is per-session.

## Verification

- WebUI: `tsc -b`; focused chat/locale tests (switch default off, flag
  sent on/off, IT/EN copy); full suite versus the captured baseline.
- Gateway: new tests cover flag-absent regression, forced read-only
  admission, terminal safety clarification, consequential command path,
  streaming fall-through, request-field default, and read-only tool
  rejection; full suite versus the 951-passed baseline.
- Live: toggle off reproduces the incident behavior; toggle on answers
  the batch question from `get_campaign_history_batch` /
  `list_campaign_history_rows`; a write command with the toggle on still
  requires the established confirmation path.
