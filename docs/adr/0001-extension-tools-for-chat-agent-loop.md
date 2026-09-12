# ADR-0001: Extension Tools for the Chat Agent Loop

- **Status:** Accepted
- **Date:** 2026-09-11
- **Deciders:** Retriva architecture
- **Scope:** retriva-gateway, retriva-core (openai_api), retriva-crm-assistant

## Context

The CRM Assistant qualification pipeline is deterministic and exposed only as
HTTP routes (`/api/v2/crm/*` on Core, proxied by the Gateway). The chat is a
plain RAG passthrough with **no tool-calling support anywhere**:

- Core's `ChatCompletionRequest` does not accept the OpenAI `tools` parameter;
- the LLM is called with a fixed system+user message pair;
- the Gateway forwards a single user message, statelessly;
- the only `tool_calls` usage is the structured-citations back-compat envelope
  (a data channel, not function calling).

The chat therefore cannot execute qualification; a conversational model asked
to qualify candidates would role-play the pipeline and invent scores, verdicts,
and evidence. We need a mechanism that lets the conversational model invoke the
deterministic pipeline, without duplicating CRM logic in the Gateway and
without letting the model choose arbitrary identifiers.

## Decision drivers

1. The chat must invoke the **existing** CRM API routes — no logic duplication.
2. The mechanism must be **reusable** by future Retriva extensions (not
   CRM-specific).
3. The model must never choose tenant/KB/attachment/session/job identifiers
   outside the trusted request context.
4. Existing plain chat behavior must remain available when no tool is invoked.
5. The Gateway already owns auth (`Principal`), correlation IDs, and the
   session/CRM proxy routes; Core's chat app is a stateless QA engine.

## Considered options

### Option A — Reusable Gateway agent loop over typed extension tools (chosen)

The Gateway gains a generic **tool registry** and an **agent loop** in its
`/chat` route. Tools are *typed operations* backed by existing Gateway proxy
routes (which in turn proxy Core/extension routes). The loop:

1. builds an OpenAI-compatible `tools` array from the registry;
2. calls the chat LLM with `tools=` (function calling);
3. executes any `tool_calls` **server-side** against the typed Gateway routes,
   injecting trusted context (session, KB, collection) and ignoring/overriding
   model-supplied identifiers where the context dictates them;
4. feeds tool results back to the LLM (bounded iterations);
5. streams or returns the final answer.

Tool definitions are contributed by extensions via a registry convention
(`*_chat_tools` capability), so the loop itself is generic.

### Option B — Open WebUI tool bindings calling typed Gateway CRM routes

Open WebUI natively supports "Tools" (Python plugins executed inside Open
WebUI) that can call the Gateway's typed CRM routes. No Gateway changes.

**Rejected:** couples the agent behavior to a specific frontend; the tool
logic (context injection, allow-lists, loop limits) would live outside Retriva
entirely; not reusable by non-Open-WebUI clients; harder to test in CI.

### Option C — Core-side agent loop in `openai_api`

Implement function calling inside Core's `/v1/chat/completions`.

**Rejected:** Core's chat app is deliberately a stateless QA engine; the
Gateway is the security and session boundary (auth terminates there; Core is
unauthenticated internally). Executing tools in Core would let the model reach
internal routes without Gateway authorization, and would couple Core to
extension-specific semantics. Also breaks the existing raw-SSE pass-through
contract with the WebUI.

## Decision

**Option A.** A generic, registry-driven tool mechanism in the Gateway:

- `retriva_gateway/agent/tools.py` — `ToolDefinition` (JSON-schema validated),
  `ToolRegistry`, per-tool execution backed by `core_client` calls to the
  **existing** Gateway proxy routes (no CRM logic in the Gateway).
- `retriva_gateway/agent/loop.py` — bounded agent loop with:
  - tool allow-list (config);
  - max tool-call iterations (`AGENT_MAX_TOOL_ITERATIONS`, default 6);
  - per-call timeout (`AGENT_TOOL_TIMEOUT_SECONDS`, default 120);
  - recursion protection (a tool result is never re-executed; identical
    repeated calls are detected and short-circuited);
  - correlation-ID propagation into every tool execution;
  - cancellation via request disconnect;
  - trusted-context injection: `session_id`, `kb_id`, `attachment_id` come
    from the request context, never from model output (model may only select
    among attachment IDs listed in the session).
- Extensions register chat tools via the existing `CapabilityRegistry`
  convention: a capability named `crm_chat_tools` (suffix `_chat_tools`)
  exposing `get_tools() -> list[ToolDefinition]`. The Gateway fetches tool
  definitions from Core at chat time (capability discovery endpoint) so the
  Gateway stays extension-agnostic.

## Consequences

- **Positive:** no CRM logic in the Gateway; any future extension can expose
  chat tools by registering a `*_chat_tools` capability; plain chat unchanged
  when the model emits no tool calls; auth/correlation enforced centrally.
- **Costs:** the Gateway now calls the chat LLM with `tools=` (Core's
  `/v1/chat/completions` must accept and forward `tools`/`tool_choice`);
  the loop adds latency when tools are used.
- **Security:** model-supplied identifiers are validated against the request
  context (session ownership, KB allow-list); arbitrary internal routes are
  not exposed — only registered, schema-validated tools.
- **Backward compatibility:** `ChatRequest` gains optional fields
  (`session_id`, `tools_enabled`); absent fields → behavior identical to
  today. Core's chat endpoint ignores `tools` for non-agent callers.