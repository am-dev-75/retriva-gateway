# Catalog-Driven Semantic Routing — Rollout Record

- **Spec:** [040 — Catalog-Driven Semantic Intent Router](specs/040-catalog-driven-semantic-routing/spec.md)
- **ADR:** [ADR-045](adr/adr-045-catalog-driven-semantic-routing.md)
- **Status:** Phase E executed 2026-11-06; active in the owner-controlled
  environment. Gate E delivery acceptance pending.
- **Owner authorization:** Gate D PASSED 2026-11-06. The owner reviewed the
  shadow evidence and authorized active rollout in the controlled
  environment. This record formalizes that decision in the governance pack.
  Owner's words (2026-11-06): *“We can enable the hybrid intent
  detector/router. Retriva is still used by selected users in a controlled
  environment so it is safe to do that.”*
- **Registry:** Spec 040 remains `accepted`; the registry has no
  `implemented`/`complete` status in its accepted vocabulary, so the
  implementation is recorded here rather than by a status change.

## 1. Rollout summary

| Item | Value |
|---|---|
| `AGENT_INTENT_ROUTER_MODE` | `active` |
| `AGENT_SEMANTIC_ROUTER_ENABLED` | `true` |
| `AGENT_INTENT_CLASSIFIER_ENABLED` | `true` |
| `AGENT_SEMANTIC_ROUTER_MIN_CONFIDENCE` | `0.85` |
| `AGENT_SEMANTIC_ROUTER_FAMILY_MIN_CONFIDENCE` | `0.85` |
| Runtime env change | 2026-11-06 11:38–11:39 +01 (`.env`, `.env.cust_0007`; uncommitted runtime state) |
| Gateway container created | 2026-11-06T14:29:00Z |
| Transport | Core `/v1/intent/classification`, schema/prompt v2 |

The committed templates remain safe-by-default (`AGENT_SEMANTIC_ROUTER_ENABLED=false`,
mode `off`); the active state is the owner-controlled runtime configuration.

## 2. Shadow evidence (Gate D)

- Dataset v2 and runner: `eval/hybrid_intent_routing/dataset-v2.jsonl`,
  `run_router_shadow.py`; report
  `eval/hybrid_intent_routing/reports/router_shadow_report.json`.
- Results reviewed by the owner:
  - 20/20 router decision accuracy;
  - zero destructive executions;
  - zero router-routed tool calls;
  - zero shadow route changes;
  - incident question (`Quante aziende abbiamo indirizzato nella campagna
    2026-CRA-IT?`) classified `FAMILY`/`CAMPAIGN` at confidence 1.0 while
    the served route stayed `CLARIFY`.
- Gate D outcome: **PASSED 2026-11-06**.

## 3. Rollback proof

Rollback is `AGENT_INTENT_ROUTER_MODE=off` **and**
`AGENT_SEMANTIC_ROUTER_ENABLED=false`, followed by a gateway recreate
(`docker compose up -d`; a plain restart does not reload environment).

- With mode `off` and/or the router flag off, the routing path is the
  deterministic/legacy path and no semantic router call is made.
- Phase C tests prove the matrix:
  `test_mode_off_or_flag_off_is_exact_legacy` (off/shadow/active × flag
  on/off), `test_router_disabled_never_calls_transport`, and the
  deterministic safety golden corpus
  (`test_deterministic_safety_outcomes_byte_identical`).
- The rollback does not require a migration; no data was written by the
  router.

## 4. Deployed walkthrough (2026-11-06)

In active mode, with the same runtime used by the WebUI:

- `Quante aziende abbiamo indirizzato nella campagna 2026-CRA-IT?`
  → answered from the campaign data path (446 companies) via
  `get_campaign_company_stats`; `semantic_router decision=FAMILY
  family=CAMPAIGN confidence=1.0`.
- `How many outreach campaigns have we done?` → deterministic
  `CAMPAIGN_COUNT` fast path (1 completed campaign) via `list_campaigns`.
- A knowledge-base question → cited RAG response.
- A negated write (`Non creare una nuova campagna.`) → no tool, no write.
- Italian campaign export (`Esporta in un file Excel le aziende che
  appartengono alla campagna 2026-CRA-IT.`) → Italian answer, FAMILY/CAMPAIGN,
  `export_campaign_companies` read-only tool, 446-company XLSX session
  artifact, download path returned; canonical tables unchanged and no
  knowledge-base ingestion.
- English campaign export → English answer with the same 446-company
  artifact path.
- Italian out-of-catalog action (PowerPoint) → honest Italian answer that
  PPT is not available; no tool and no substituted artifact.
- Rollback steps remain available as above.

## 5. Post-rollout incident evidence

On 2026-11-06 the owner asked in Italian:

> Esporta in un file Excel le aziende che appartengono alla campagna 2026-CRA-IT.

Retriva served the English semantic-router clarify:

> I can answer that from the knowledge base or from a read-only Company
> Intelligence workflow, but I could not choose a safe data plane. Please
> rephrase, or name the campaign or workflow family.

Trace: gateway correlation `96eedd3c-90da-45f7-926a-2bcac727c93d`,
`semantic_router decision=CLARIFY confidence=0.8 shadow=False`; the v2
router returned `language="it"` and `reason_codes=["EXPLICIT_ACTION_VERB"]`.
The deterministic pipeline produced `AMBIGUOUS`/`WORKFLOW_ADJACENT` and the
message entered the router band; the campaign code was already named.

Verdict: structurally coherent (fail-closed `CLARIFY`; no write, no
invented export), but two UX/design defects were confirmed: the static
English clarify template ignores the router's `language`, and its wording
asks to name an already-named campaign instead of stating that export is
not an available read-only capability. Remediation (localization,
reason-aware wording, and a governed campaign-companies XLSX export) is
tracked separately; the freeze (no new deterministic recall vocabulary)
remains in force.

## 6. Follow-up delivery (2026-11-06)

- Deterministic templates are localized EN/IT (`core/routing/messages.py`;
  `clarifications.py`, router templates, streaming refusal, qualification/
  agent errors, and agent-loop fallbacks/tool errors). Unsupported languages
  fall back to English.
- The semantic-router clarify is reason-aware: `EXPLICIT_ACTION_VERB`
  states that the action is not an available read-only capability and lists
  the family reads instead of asking to name an already-named campaign.
- `export_campaign_companies` is a read-only CAMPAIGN tool (destructive=False)
  that exports the campaign companies to an XLSX session artifact via the
  session-artifact service; the CAMPAIGN card auto-derives it. Core prompt
  v2 now states that FAMILY includes an export only when the requested
  artifact type is offered by a catalog tool; prompt_version stays `2`.
- Eval dataset v2 includes the Italian/English export records; the offline
  gate passes.

## 7. Residual risks

- The PowerPoint/out-of-catalog action was answered honestly in Italian by
  the agent loop (no tool, no fabricated PPT) rather than the deterministic
  action clarify; the action clarify itself is covered by unit tests and is
  used when the router returns `CLARIFY` + `EXPLICIT_ACTION_VERB`.
- The monitor can read the unacked depth but not message payloads; `promtool`
  is not available locally, so the monitoring alert is YAML-shape-validated
  only.
- Campaign-company identifiers are empty for the current 446-company export
  because those organizations have no stored identifiers; the column is
  present for tenants that do.
