# Chat qualification readiness alignment

## Defect and ownership

The chat agent refused workbook qualification after seeing `IDENTITY_ONLY`.
Two active orchestration surfaces were stale:

- `agent/loop.py` coupled the assistant to KB-selected ACP/CCO and blanket
  public-research readiness refusal.
- CRM `api.readiness` unconditionally emitted
  `WEB_RESEARCH_CAPABILITY_INSUFFICIENT` for `NONE`/`IDENTITY_ONLY`, whereas
  `CrmAssistantService.qualify` already admits those capabilities when
  official-site research is enabled.

The readiness endpoint now mirrors that existing admission policy. Production
provider availability and usable active global ACP/CCO remain job-level gates.
Degraded external discovery remains visible in research metadata and warnings.
When official-site research is disabled and external discovery is unavailable,
the capability blocker is retained. No candidate capability logic was changed.

The chat recognizes requests, selects a session attachment, invokes
`qualify_candidates`, and presents official progress/results. The workflow owns
parsing, website extraction/verification, candidate capability, research-path
selection, deferral, and ACP/CCO assessment. The chat must not inspect candidates
before admission or invent a direct-mode fallback. Empty attachment context is
rejected by the tool executor, not only by the prompt.

## Prompt audit

- Gateway `AGENT_SYSTEM_PROMPT`: revised global binding, blockers, ownership,
  capability warnings, and mandatory workflow invocation where eligible.
- `get_qualification_readiness` and `qualify_candidates` descriptions: aligned.
- Customer `qualification_prompt.md`: obsolete KB-selection and full-refusal
  wording revised. The corresponding `qualification_prompt.txt` acceptance
  input delegates research decisions to the workflow.
- CRM task prompts are extraction/assessment prompts, not chat orchestration.
  They and the workflow were left unchanged.
- Core `SYSTEM_PROMPT_OVERRIDE` configures grounded QA. Tool-bearing requests
  bypass that prompt construction; changing it does not update the agent.
- No programmatic GENERAL_WEB gate existed in the generic agent loop or tool
  executor. Readiness sequencing remains a model orchestration instruction;
  authoritative qualification validation remains in the backend.

## Validation scope

`tests/test_chat_qualification_policy.py` has ten deterministic cases using the
real Gateway chat adapter, agent loop, registry, schema validation and executors,
with mocked model responses and outbound CRM HTTP. It covers healthy/degraded,
verified/unparsed/mixed inputs, missing ACP/CCO, missing attachment, service
failure, unchanged strict-harness invocation detection, and no autonomous direct
fallback. The sibling-harness integration skips if that repository is absent.

CRM `tests/test_chat_readiness.py` tests eight actual readiness computations,
including true blockers and degraded capabilities with official-site research
on/off. No live Web Research is used by these new tests.

Mocked model responses prove transport and orchestration mechanics, not a real
model's semantic compliance with prompts. A separate live strict-chat run through
the unchanged E2E harness is required. The harness's normal binding, terminal
state and artifact acceptance checks still apply; tool invocation alone is not
reported as a completed qualification pass.

Unchanged: E2E harness, candidate research/scoring, ACP/CCO data and resolution,
SearXNG configuration, official-site research, and report generation.
