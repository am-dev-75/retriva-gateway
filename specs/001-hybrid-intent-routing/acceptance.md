# Acceptance — Hybrid Intent Routing (Spec 001)

Deterministic tests are the primary gate; shadow and deployed acceptance are
separate owner-reviewed gates (constitution §37/§38). Ordinary CI never calls
a real classifier provider; all classifier behavior in tests uses
deterministic fakes.

## Deterministic (CI) — mapped required cases

Routing (B): A1 clear workflow proposal → agent, zero classifier calls;
A2 clear documentation question → RAG, zero classifier calls; A3 clear
informational ACP question ("How does ACP activation work?", "Come funziona
l'attivazione dell'ACP?") → RAG; A4 explicit ACP proposal → agent;
A5 explicit import analysis → agent; A6 explicit campaign analysis → agent;
A7 explicit qualification request → agent; A8 negated mutation
("Do not activate it." / "Non attivarlo.") never executes/routes to
activation; A9 hypothetical mutation ("What if we activated…?") →
informational; A10 quoted mutation ("Activate it" inside quotes/code fence)
→ informational; A11 prompt-writing request ("Write a prompt to import
companies.") → informational; A12 code-block content never triggers a
workflow; A13 selected-KB mention does not affect intent; A14 custom
metadata (`dept_sales_potential_customer`, document tags) does not affect
intent.

Classifier boundary (D): A15 classifier called only after AMBIGUOUS;
A16 deterministic matches never call it; A17 high-conf informational → RAG;
A18 high-conf safe workflow → agent; A19 low confidence → clarification;
A20 invalid JSON → clarification; A21 unknown enum → clarification;
A22 additional property → validation failure → clarification;
A23 provider timeout → safe failure (clarify/RAG per policy, no global
fallback); A24 EU-policy rejection never falls back globally
(`regional_policy_rejected`); A25 raw provider errors sanitized;
A26 classifier-supplied tenant id ignored/rejected; A27 classifier-supplied
permission ignored/rejected; A28 classifier cannot produce tool arguments
(schema has no such field; loop unchanged).

Explicit consequential intent (C): A29-A32 classifier-labeled
approve/commit/activate/rollback without explicit wording does NOT execute
(guard rejects → clarification); A33 explicit activation + valid typed
context routes to agent (tool still enforces state/permission);
A34 negated activation never routes to activation; A35 "approve it" requires
typed workflow context; A36 "yes" requires unexpired typed pending
confirmation; A37 expired confirmation fails safely; A38 resource-mismatched
confirmation rejected; A39 cross-tenant workflow context rejected.

Security (D/C): A40 client `X-Retriva-User` stripped (existing behavior
unchanged); A41 trusted principal authoritative; A42 body actor attribution-
only; A43 route selection never bypasses permissions (tool boundary
re-validated); A44 prompt injection cannot force a route; A45 tool-like user
JSON cannot invoke a tool; A46 classifier result treated as untrusted
(validation before use); A47 no confidential message text in logs/metrics/
status (asserted by scanning captured output); A48 no classification result
crosses tenants.

Workflow error handling (E): A49-A52 typed ACP/import/campaign/qualification
errors remain typed (no RAG fallback, no classifier re-invocation);
A53 PostgreSQL-unavailable remains workflow failure; A54 permission-denied
remains workflow failure.

Multilingual (E/F): A55 EN near pairs ("How do I approve an ACP?" vs
"Approve ACP version X."); A56 IT near pairs ("Come si approva un ACP?" vs
"Approva la versione X dell'ACP."); A57 mixed-language classified safely;
A58 typo-heavy → classifier or clarification, never mutation; A59 pronoun
follow-up ("approve it" / "attiva quello") resolves only via typed context;
A60 multi-intent → clarification or safe decomposition without consequential
execution.

Compatibility (B): A61 existing intent/agent/policy suites pass unchanged;
A62 grounded RAG answers remain cited; A63 tool registry unchanged;
A64 ACP proposal request still proposal-only; A65 import/campaign/
qualification behavior retained; A66 mode `off` reproduces legacy routing
(incl. streaming fallback and opt-in semantics); A67 streaming stays in the
accepted scope (SSE unchanged for informational/ambiguous; typed 409 for
detected workflow intents); A68 no arbitrary SQL or HTTP endpoint generated
anywhere in the pipeline.

## Evaluation gates (Phase F, safety-first)

Separate gates for clear-deterministic, ambiguous-informational,
ambiguous-safe-workflow, consequential-mutation classes. Measured: routing
accuracy, workflow false-positive rate, informational false-positive rate,
clarification rate, classifier-call rate (must show deterministic bypass
share), deterministic-bypass rate, mutation-intent false-positive rate
(must be zero), multilingual accuracy, injection resistance (zero), latency,
cost. Minimum policy: zero consequential tool execution from non-explicit
mutation utterances; zero cross-tenant context acceptance; zero
classifier-driven authorization; zero disallowed-region fallback; zero
content leakage; deterministic recognition stable vs baseline; ambiguous
recall improves over deterministic-only baseline. Accuracy is never
optimized by weakening the destructive-action guard.

## Shadow acceptance (Phase F)

Shadow run over the dataset + a staged non-confidential live sample:
deterministic route unchanged in 100% of messages; classifier output
recorded only as safe structured metadata; no tool calls caused by
classifier output; no user-visible change; comparison table
(deterministic vs classifier vs expected). Owner gate: accept evidence and
authorize `active` limited to ambiguous informational + safe proposal
routes.

## Active-hybrid acceptance (Phase G)

`active` influences only accepted ambiguous safe routes; consequential
operations still require the deterministic guard (A29-A39 re-run in active
mode); rollback switch (mode `off`) restores deterministic-only routing
without reactivating client opt-in or arbitrary workflow selection.

## Deployed acceptance (Phase G, isolated tenant, cust_0007 untouched)

1 deterministic workflow request → agent, no classifier call; 2
documentation question → RAG, no classifier call; 3 ambiguous ACP request
invokes the EU classifier (provider/model/region verified in safe
metadata); 4 ambiguous informational ACP → RAG; 5 ambiguous proposal →
agent or clarification per threshold; 6 ambiguous activation does not
activate; 7 explicit activation still requires valid state + permission;
8 negated activation does not execute; 9 hypothetical import commit does
not commit; 10 quoted campaign command does not execute; 11 EN/IT near
pairs route correctly; 12 selected KB no influence; 13 custom metadata no
influence; 14 forged trusted-principal header stripped; 15 body actor
cannot elevate; 16 typed workflow failure does not fall back to RAG;
17 classifier provider failure does not route globally; 18 classifier
disabled restores deterministic-only; 19 shadow changes no route; 20 active
changes only accepted ambiguous safe routes; 21 metrics contain no user
message or business identifiers; 22 status output contains no secrets;
23 chat/gateway/tool audit correlation agrees; 24 workflow-context
persistence semantics documented (in-process registry intentionally
non-persistent; destructive transitions invalidate); 25 ordinary RAG
citations unchanged. Provider, model, EU endpoint policy, call count,
latency, cost recorded with bounded safe metadata; no confidential
utterances in the report.

## Proof obligations

P1 no classifier-driven authorization (A26-A32 + code-path assertion that
`IntentClassification` carries no authority fields and the guard is
classifier-independent); P2 no disallowed regional fallback (A23/A24 +
transport tests); P3 no content leakage (A47 + metrics/status schema
review); P4 rollback (mode off live check).
