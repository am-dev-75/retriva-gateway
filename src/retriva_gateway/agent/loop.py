# Copyright (C) 2026 Andrea Marson (am.dev.75@gmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Bounded agent loop for the Gateway chat.

Implements the OpenAI function-calling loop server-side:

1. build the `tools` array from the typed tool registry;
2. call the chat LLM (via Core's /v1/chat/completions) with `tools=`;
3. execute any `tool_calls` against the typed tools with trusted context;
4. feed tool results back to the LLM (bounded iterations);
5. return the final assistant message.

Safety properties:
- tool allow-list (config);
- max iterations (AGENT_MAX_TOOL_ITERATIONS);
- per-call timeout (AGENT_TOOL_TIMEOUT_SECONDS);
- recursion protection: identical repeated tool calls are detected and
  short-circuited with an explanatory result instead of re-executing;
- trusted-context injection: session/KB/attachment identifiers come from the
  authenticated request, never from model output;
- correlation IDs propagate into every tool execution and log line;
- the model is instructed (system prompt) to never simulate qualification.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from retriva_gateway.agent.tools import (
    ToolContext,
    ToolDefinition,
    ToolExecutionError,
    ToolRegistry,
    _validate_against_schema,
)
from retriva_gateway.config import settings
from retriva_gateway.core.client import core_client
from retriva_gateway.core.context import get_correlation_id


AGENT_SYSTEM_PROMPT = """You are the conversational interface for Retriva CRM Assistant.

Your role is to help users qualify prospective companies against the
Average Customer Profile (ACP) and Company Commercial Offering (CCO) of the
selected Retriva knowledge base, using the deterministic CRM Assistant
qualification tools.  The ACP describes recurring characteristics observed
among the reference organizations; it is not an ideal or normative target
profile. You must orchestrate the tools; you must NEVER simulate qualification,
invent evidence, calculate unofficial scores, or make unsupported judgments.

Operating rules:
1. All official identity resolution, public web research, GraphRAG analysis,
   scoring, verdict assignment, and report generation are performed by the
   deterministic qualification pipeline invoked through your tools.
2. Before qualifying, call `get_qualification_readiness`. If readiness
   reports that public research is not ready (e.g. mock-only providers), stop
   and report the configuration error. Do not proceed with qualification.
3. To qualify, call `qualify_candidates` with an attachment_id that belongs
   to the current session. If the response status is `already_running`, use
   the returned job_id — do NOT start another job.
4. MULTI-TURN JOB LIFECYCLE (the tool-call limit applies to ONE turn):
   - Turn 1: start the job, report the job_id and initial status, then STOP.
     A running job is NOT a reason to keep polling — return and let the
     backend continue.
   - Turn 2 (user asks for status): call `list_qualification_jobs` to find
     the session's jobs server-side (do not guess job IDs), then call
     `get_qualification_job` ONCE and report the official state. Do not
     poll repeatedly within the turn.
   - Turn 3 (job complete): call `get_qualification_results`,
     `get_qualification_report`, and `get_qualification_artifacts` to
     retrieve official results and artifact references.
   Never consume all tool iterations polling a long-running job; identical
   repeated `get_qualification_job` calls are rejected by the loop.
5. Use ONLY the scores and verdicts returned by the pipeline. Pipeline scores
   are in the range 0.0-1.0; display them as 0-100 ONLY by multiplying by
   100 (e.g. 0.84 -> 84/100). Do not otherwise normalize, combine, reweight,
   or recalculate official scores.
6. Official verdicts are: STRONG_FIT, POSSIBLE_FIT, WEAK_FIT, NOT_A_FIT,
   INSUFFICIENT_EVIDENCE, IDENTITY_UNRESOLVED, EXTRACTION_REVIEW_REQUIRED,
   NO_OFFERING. NO_OFFERING is a REDUCED assessment (no usable Offering
   Portfolio was available); never convert it into NOT_A_FIT.
7. A low score caused by missing information is NOT evidence of poor fit.
   The pipeline excludes unevaluated ACP dimensions from weighted averages;
   report unknown dimensions as unknowns, not as negative evidence.
8. Distinguish clearly: public facts, GraphRAG-derived relationships, ACP
   comparisons, CCO information, commercial hypotheses, unknowns, conflicting
   evidence, and pipeline warnings. Use cautious language ("may indicate",
   "appears consistent with", "requires human validation").
9. Report candidate truncation explicitly: state total candidates extracted,
   processed, and pending/unprocessed because of configured limits.
10. Keep all candidate information scoped to the current chat session. Never
    request ingestion of candidate documents into the persistent knowledge
    base. Never send emails or start outbound campaigns.
11. If the required tools are unavailable or fail, say clearly that candidate
    qualification cannot be executed from this chat and that you will not
    simulate scores or research results.
12. Respond in the user's language. Do not translate identifiers, legal
    names, VAT IDs, source URLs, or official offering names.
"""


class AgentLoopError(Exception):
    """Raised when the agent loop cannot proceed."""


class AgentLoopResult:
    def __init__(
        self,
        content: str,
        *,
        tool_calls_executed: List[Dict[str, Any]],
        iterations: int,
        stopped_reason: str,
    ) -> None:
        self.content = content
        self.tool_calls_executed = tool_calls_executed
        self.iterations = iterations
        self.stopped_reason = stopped_reason


def _extract_tool_calls(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    calls = message.get("tool_calls") or []
    out = []
    for call in calls:
        fn = call.get("function") or {}
        name = fn.get("name", "")
        raw_args = fn.get("arguments") or "{}"
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except (TypeError, json.JSONDecodeError):
            args = {}
        if not isinstance(args, dict):
            args = {}
        out.append({"id": call.get("id", f"call_{name}"), "name": name, "args": args})
    return out


async def _execute_tool(
    tool: ToolDefinition,
    call: Dict[str, Any],
    ctx: ToolContext,
    tool_timeout: float,
) -> Dict[str, Any]:
    """Validate and execute one tool call with trusted context."""
    args = call["args"]
    schema_err = _validate_against_schema(args, tool.parameters)
    if schema_err:
        return {"error": {"code": "invalid_arguments", "message": schema_err}}
    try:
        return await asyncio.wait_for(tool.execute(args, ctx), timeout=tool_timeout)
    except asyncio.TimeoutError:
        return {"error": {"code": "tool_timeout",
                          "message": f"Tool {tool.name} timed out after {tool_timeout}s."}}
    except ToolExecutionError as e:
        return {"error": {"code": e.code, "message": e.message}}
    except Exception as e:  # noqa: BLE001 — tool boundary
        logger.exception(f"[{ctx.correlation_id}] tool {tool.name} crashed")
        return {"error": {"code": "tool_crash", "message": str(e)[:500]}}


async def run_agent_loop(
    *,
    user_message: str,
    registry: ToolRegistry,
    ctx: ToolContext,
    kb_ids: List[str],
    metadata_filters: Optional[List[Dict[str, Any]]] = None,
    metadata_filter_mode: str = "soft",
    history: Optional[List[Dict[str, str]]] = None,
    max_iterations: Optional[int] = None,
    tool_timeout_s: Optional[float] = None,
) -> AgentLoopResult:
    """Run the bounded tool-calling loop and return the final message.

    The loop is bounded by AGENT_MAX_TOOL_ITERATIONS; identical repeated
    tool calls are short-circuited (recursion protection); every tool
    execution is schema-validated, allow-listed, timeout-bounded, and
    executed with the trusted ToolContext (never model-supplied identity).
    """
    corr_id = get_correlation_id() or "unknown"
    max_iterations = settings.AGENT_MAX_TOOL_ITERATIONS
    tool_timeout = float(settings.AGENT_TOOL_TIMEOUT_SECONDS)
    allowed = settings.AGENT_TOOL_ALLOWLIST or None

    tools_schema = registry.openai_schema(allowed)
    if not tools_schema:
        raise AgentLoopError("No chat tools are registered; agent mode unavailable.")

    messages: List[Dict[str, Any]] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    # Trusted session context: the model may only reference attachments that
    # belong to the current chat session (validated again at execution time).
    context_lines = [
        f"- session_id: {ctx.session_id}",
        f"- kb_id: {ctx.kb_id}",
    ]
    if ctx.allowed_attachment_ids:
        context_lines.append(
            "- attachments available in this session (attachment_id values "
            "you may pass to qualify_candidates): "
            + ", ".join(ctx.allowed_attachment_ids)
        )
    else:
        context_lines.append(
            "- attachments available in this session: NONE (ask the user to "
            "attach the candidate document)"
        )
    messages.append({
        "role": "system",
        "content": (
            "Trusted request context (authoritative; use these values in "
            "tool calls — do not invent identifiers):\n"
            + "\n".join(context_lines)
        ),
    })
    if history:
        messages.extend(history[-10:])  # bounded history
    messages.append({"role": "user", "content": user_message})

    executed: List[Dict[str, Any]] = []
    seen_calls: set = set()
    stopped_reason = "max_iterations"
    final_content = ""
    iteration = 0

    for iteration in range(1, max_iterations + 1):
        payload: Dict[str, Any] = {
            "model": "retriva",
            "messages": messages,
            "kb_ids": kb_ids,
            "metadata_filters": metadata_filters or [],
            "metadata_filter_mode": metadata_filter_mode,
            "stream": False,
            "tools": tools_schema,
            "tool_choice": "auto",
        }
        core_response = await core_client.chat_completions(payload, stream=False)
        choice = (core_response.get("choices") or [{}])[0]
        message = choice.get("message", {}) or {}
        content = message.get("content") or ""
        tool_calls = _extract_tool_calls(message)

        if not tool_calls:
            final_content = content
            stopped_reason = "final_answer"
            break

        messages.append({"role": "assistant", "content": content or "",
                         "tool_calls": message.get("tool_calls")})

        for call in tool_calls:
            name = call["name"]
            tool = registry.get(name)
            call_sig = (name, json.dumps(call["args"], sort_keys=True))
            if tool is None or (allowed is not None and name not in allowed):
                result = {"error": {"code": "tool_not_allowed",
                                    "message": f"Tool {name!r} is not available."}}
            elif call_sig in seen_calls:
                # Recursion protection: identical repeated call.
                result = {"error": {
                    "code": "repeated_call",
                    "message": (
                        f"Tool {name!r} was already called with identical "
                        "arguments. Use the previous result; do not repeat "
                        "the same call."
                    ),
                }}
            else:
                seen_calls.add(call_sig)
                t0 = time.monotonic()
                result = await _execute_tool(tool, call, ctx, tool_timeout=tool_timeout)
                logger.info(
                    f"[{corr_id}] agent tool {name} iter={iteration} "
                    f"took {time.monotonic() - t0:.2f}s"
                )
            executed.append({
                "iteration": iteration,
                "tool": name,
                "args": call["args"],
                # Tool errors use the shape {"error": {"code", "message"}}.
                # Upstream payloads may legitimately contain an "error" key
                # (e.g. job status "error": null) — only a dict-valued
                # "error" counts as a tool failure.
                "ok": not (
                    isinstance(result, dict)
                    and isinstance(result.get("error"), dict)
                ),
            })
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(result, ensure_ascii=False, default=str)[:50000],
            })
    else:
        stopped_reason = "max_iterations"
        final_content = (
            "The qualification conversation reached the tool-call limit "
            f"({max_iterations} iterations) before a final answer was "
            "produced. Please ask for the current job status to continue."
        )

    return AgentLoopResult(
        content=final_content,
        tool_calls_executed=executed,
        iterations=iteration,
        stopped_reason=stopped_reason,
    )