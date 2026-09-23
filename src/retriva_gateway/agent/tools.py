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
Generic typed tools for the Gateway chat agent loop.

Tools are *typed operations* backed by the Gateway's existing proxy routes
(which proxy Core / extension routes).  The Gateway contains NO CRM
qualification logic — it only forwards validated, schema-checked calls.

Design rules (see docs/adr/0001-extension-tools-for-chat-agent-loop.md):

- Tool definitions are JSON-schema validated before execution.
- Trusted context (session_id, kb_id, collection) is injected by the loop;
  the model may only SELECT among identifiers exposed in the request context
  (e.g. attachment IDs listed for the current session).  Model-supplied
  identifiers that are not in the trusted set are rejected.
- Arbitrary internal HTTP routes are never exposed; only registered tools.
- Every tool result is JSON-serializable and bounded in size.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Dict, List, Optional

from loguru import logger

from retriva_gateway.core.client import core_client
from retriva_gateway.core.context import get_correlation_id


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

@dataclass
class ToolDefinition:
    """A typed chat tool with a JSON-schema parameter contract."""

    name: str
    description: str
    # JSON schema for the `parameters` object (OpenAI function-calling shape).
    parameters: Dict[str, Any]
    # Async executor: (arguments, ctx) -> JSON-serializable result.
    # `ctx` is a TrustedContext; executors MUST use it over model input.
    execute: Callable[[Dict[str, Any], "ToolContext"], Awaitable[Dict[str, Any]]]
    # Whether the tool mutates state (used for extra logging/allow-lists).
    destructive: bool = False


@dataclass
class ToolContext:
    """Trusted request context injected into every tool execution.

    The model never supplies these values; they come from the authenticated
    request.  `allowed_attachment_ids` bounds which attachments the model
    may reference (session-scoped).
    """

    session_id: str
    kb_id: str
    collection_name: str = ""
    allowed_attachment_ids: List[str] = field(default_factory=list)
    correlation_id: str = ""


class ToolExecutionError(Exception):
    """Raised when a tool call cannot be executed as requested."""

    def __init__(self, code: str, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_against_schema(args: Dict[str, Any], schema: Dict[str, Any]) -> Optional[str]:
    """Lightweight JSON-schema validation (type/required/enum).

    Avoids a hard jsonschema dependency; covers the subset used by the
    registered tools.  Returns an error message or None.
    """
    if schema.get("type") != "object":
        return "tool parameters schema must be an object"
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    for key in required:
        if key not in args:
            return f"missing required parameter: {key}"
    for key, value in args.items():
        if key not in properties:
            return f"unknown parameter: {key}"
        prop = properties[key]
        expected = prop.get("type")
        if expected == "string" and not isinstance(value, str):
            return f"parameter {key} must be a string"
        if expected == "integer" and not isinstance(value, int):
            return f"parameter {key} must be an integer"
        if expected == "boolean" and not isinstance(value, bool):
            return f"parameter {key} must be a boolean"
        if expected == "array" and not isinstance(value, list):
            return f"parameter {key} must be a list"
        if "enum" in prop and value not in prop["enum"]:
            return f"parameter {key} must be one of {prop['enum']}"
    return None


def _validate_context_identifier(
    value: str,
    allowed: List[str],
    what: str,
) -> None:
    """Reject model-supplied identifiers outside the trusted context."""
    if value and allowed and value not in allowed:
        raise ToolExecutionError(
            "identifier_not_allowed",
            f"The supplied {what} is not part of the current trusted "
            "request context. Choose one of the identifiers provided in "
            "the session context.",
            http_status=403,
        )


# ---------------------------------------------------------------------------
# CRM Assistant tools (backed by the EXISTING Gateway CRM proxy routes)
# ---------------------------------------------------------------------------

async def _crm_request(method: str, path: str, **kwargs) -> Dict[str, Any]:
    """Call Core's ingestion API via the shared core_client (no CRM logic)."""
    import httpx
    try:
        resp = await core_client._request(method, core_client.ingestion_base_url, path, **kwargs)
        return resp.json()
    except httpx.HTTPStatusError as e:
        detail = e.response.text[:500]
        raise ToolExecutionError(
            "upstream_error",
            f"CRM API returned {e.response.status_code}: {detail}",
            http_status=e.response.status_code,
        )


async def _tool_qualify_candidates(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    attachment_id = args.get("attachment_id", "")
    if not attachment_id or not ctx.allowed_attachment_ids:
        raise ToolExecutionError(
            "missing_attachment",
            "Attach a supported candidate workbook to the current chat session first.",
        )
    if attachment_id not in ctx.allowed_attachment_ids:
        raise ToolExecutionError(
            "identifier_not_allowed",
            "attachment_id is not an attachment of the current chat session.",
            http_status=403,
        )
    payload: Dict[str, Any] = {
        "session_id": ctx.session_id,
        "attachment_id": attachment_id,
        "kb_id": ctx.kb_id,
    }
    if ctx.collection_name:
        payload["collection_name"] = ctx.collection_name
    result = await _crm_request("POST", "/api/v2/crm/qualify", json=payload)
    # Duplicate-job protection: the backend returns the EXISTING job when a
    # non-terminal job for the same (session, attachment, KB) is already
    # running.  Surface this explicitly so the model monitors instead of
    # retrying.
    if result.get("status") == "already_running":
        result["note"] = (
            "A qualification job for this attachment is already running in "
            "this session. Monitor it with get_qualification_job instead of "
            "starting a new one."
        )
    return result


async def _tool_list_qualification_jobs(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """List THIS session's qualification jobs (trusted session context).

    Enables cross-turn job resumption: the model does not need to remember
    job IDs from conversation text — the backend associates jobs with the
    trusted session server-side.
    """
    return await _crm_request(
        "GET", f"/api/v2/crm/sessions/{ctx.session_id}/jobs"
    )


async def _get_owned_job(job_id: str, ctx: ToolContext) -> Dict[str, Any]:
    """Fetch a job and enforce SERVER-SIDE session ownership.

    The job record carries the session_id that created it.  A tool call from
    a different chat session is rejected with 403 BEFORE any job data is
    returned.  This is enforced in the tool executor (server-side), not by
    the system prompt — the model cannot talk its way past it.
    """
    job = await _crm_request("GET", f"/api/v2/crm/jobs/{job_id}")
    job_session = job.get("session_id") or ""
    if job_session and ctx.session_id and job_session != ctx.session_id:
        raise ToolExecutionError(
            "job_not_in_session",
            "This qualification job does not belong to the current chat "
            "session.",
            http_status=403,
        )
    return job


async def _tool_get_qualification_job(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    job_id = args.get("job_id", "")
    if not job_id or not job_id.startswith("job_"):
        raise ToolExecutionError("invalid_job_id", "job_id must be a job identifier returned by qualify_candidates")
    return await _get_owned_job(job_id, ctx)


async def _tool_get_qualification_results(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    job_id = args.get("job_id", "")
    if not job_id or not job_id.startswith("job_"):
        raise ToolExecutionError("invalid_job_id", "job_id must be a job identifier returned by qualify_candidates")
    # Ownership is enforced inside the results endpoint via the job lookup
    # below; the results route itself is only reachable for owned jobs.
    await _get_owned_job(job_id, ctx)
    return await _crm_request("GET", f"/api/v2/crm/jobs/{job_id}/results")


async def _tool_get_qualification_report(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """Fetch the Markdown report content for a completed job."""
    job_id = args.get("job_id", "")
    if not job_id or not job_id.startswith("job_"):
        raise ToolExecutionError("invalid_job_id", "job_id must be a job identifier returned by qualify_candidates")
    job = await _get_owned_job(job_id, ctx)
    artifact_ids = job.get("artifact_ids") or []
    if not artifact_ids:
        return {"job_id": job_id, "report": None,
                "note": "No report artifacts available for this job."}
    session_id = job.get("session_id", ctx.session_id)
    # The first artifact is the Markdown report (store_report order).
    # Artifact content is binary — fetch raw via core_client.
    resp = await core_client._request(
        "GET", core_client.ingestion_base_url,
        f"/api/v2/sessions/{session_id}/artifacts/{artifact_ids[0]}/content",
    )
    text = resp.content.decode("utf-8", errors="replace")
    # Bound the tool result: the full report is downloadable as an artifact.
    max_chars = 20000
    truncated = len(text) > max_chars
    return {
        "job_id": job_id,
        "artifact_id": artifact_ids[0],
        "media_type": "text/markdown",
        "report_markdown": text[:max_chars],
        "truncated": truncated,
        "download_hint": (
            f"Full report downloadable via session artifact {artifact_ids[0]}"
        ),
    }


async def _tool_get_qualification_artifacts(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    job_id = args.get("job_id", "")
    if not job_id or not job_id.startswith("job_"):
        raise ToolExecutionError("invalid_job_id", "job_id must be a job identifier returned by qualify_candidates")
    job = await _get_owned_job(job_id, ctx)
    session_id = job.get("session_id", ctx.session_id)
    artifacts = []
    for artifact_id in job.get("artifact_ids") or []:
        try:
            meta = await _crm_request(
                "GET", f"/api/v2/sessions/{session_id}/artifacts/{artifact_id}"
            )
        except ToolExecutionError:
            meta = {}
        artifacts.append({
            "artifact_id": artifact_id,
            "filename": meta.get("filename"),
            "media_type": meta.get("media_type"),
            "artifact_kind": meta.get("artifact_kind"),
            "download_path": f"/api/v2/sessions/{session_id}/artifacts/{artifact_id}/content",
        })
    return {"job_id": job_id, "session_id": session_id, "artifacts": artifacts}


async def _tool_cancel_qualification_job(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    job_id = args.get("job_id", "")
    if not job_id or not job_id.startswith("job_"):
        raise ToolExecutionError("invalid_job_id", "job_id must be a job identifier returned by qualify_candidates")
    # Server-side ownership check BEFORE cancelling another session's job.
    await _get_owned_job(job_id, ctx)
    # Belt-and-braces: the trusted session is also enforced by the backend
    # cancel endpoint itself.
    return await _crm_request(
        "POST", f"/api/v2/crm/jobs/{job_id}/cancel",
        params={"session_id": ctx.session_id},
    )


async def _tool_get_qualification_readiness(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """Preflight: web-research provider readiness + ACP/CCO readiness."""
    return await _crm_request("GET", "/api/v2/crm/readiness")


def build_crm_tools() -> List[ToolDefinition]:
    """Typed CRM Assistant chat tools.

    Backed exclusively by the existing CRM proxy routes; the Gateway holds
    no qualification logic.  Identifiers the model may choose are bounded:
    attachment IDs must belong to the current session; job IDs must be
    job_… identifiers previously returned by the pipeline.
    """
    return [
        ToolDefinition(
            name="get_qualification_readiness",
            description=(
                "Report qualification readiness: active GLOBAL ACP, usable "
                "authoritative GLOBAL CCO, job-level blocking_reasons, and Web "
                "Research warnings. No KB selection is required. Call BEFORE "
                "qualify_candidates. GENERAL_WEB degradation alone is not a "
                "blocker: with official-site research enabled, invoke the "
                "workflow even for an unparsed workbook. The workflow verifies "
                "domains and defers only candidates requiring unavailable "
                "external discovery. Do not infer candidate capability here. "
                "Preserve explicit job-level blockers, including mock-only "
                "configuration or unavailable qualification service."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            execute=_tool_get_qualification_readiness,
        ),
        ToolDefinition(
            name="qualify_candidates",
            description=(
                "Start the deterministic Prospect Discovery & Qualification "
                "pipeline for an attachment in the current chat session. "
                "The attachment must already be uploaded to the session. "
                "Invoke on workbook qualification requests unless readiness "
                "reports a true job-level blocker. Uses active global ACP/CCO, "
                "not a KB-selected profile. GENERAL_WEB is not mandatory when "
                "official-site research is enabled: the workflow parses the "
                "workbook, verifies supplied official websites, selects "
                "VERIFIED_DOMAIN_RESEARCH per candidate, and defers candidates "
                "requiring unavailable external discovery. Do not pre-parse "
                "or make candidate research decisions in chat. "
                "Returns a job_id for monitoring. If a job for the same "
                "attachment is already running in this session, the existing "
                "job is returned (status already_running) — do NOT start "
                "another one. Never simulates results."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "attachment_id": {
                        "type": "string",
                        "description": "Attachment ID from the current session (must be one of the session's attachments).",
                    },
                },
                "required": ["attachment_id"],
            },
            execute=_tool_qualify_candidates,
        ),
        ToolDefinition(
            name="list_qualification_jobs",
            description=(
                "List the qualification jobs of the CURRENT chat session "
                "(server-side session association — use this to find a job "
                "started in an earlier turn instead of guessing job IDs)."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            execute=_tool_list_qualification_jobs,
        ),
        ToolDefinition(
            name="get_qualification_job",
            description=(
                "Get the status of an asynchronous qualification job: state, "
                "progress, stage detail, candidate/result counts, warnings, "
                "ACP/CCO versions, analysis mode."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID returned by qualify_candidates."},
                },
                "required": ["job_id"],
            },
            execute=_tool_get_qualification_job,
        ),
        ToolDefinition(
            name="get_qualification_results",
            description=(
                "Retrieve the structured qualification results of a "
                "COMPLETED job: per-candidate official scores (0.0-1.0), "
                "official verdicts, evidence, extraction/truncation stats, "
                "and artifact references. Never invent or recompute scores."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID returned by qualify_candidates."},
                },
                "required": ["job_id"],
            },
            execute=_tool_get_qualification_results,
        ),
        ToolDefinition(
            name="get_qualification_report",
            description=(
                "Retrieve the official Markdown qualification report of a "
                "completed job (bounded excerpt; full report downloadable "
                "as a session artifact)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID returned by qualify_candidates."},
                },
                "required": ["job_id"],
            },
            execute=_tool_get_qualification_report,
        ),
        ToolDefinition(
            name="get_qualification_artifacts",
            description=(
                "List the artifacts generated by a qualification job "
                "(qualification_report.md, qualification_report.xlsx) with "
                "type, filename, media type, and download reference."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID returned by qualify_candidates."},
                },
                "required": ["job_id"],
            },
            execute=_tool_get_qualification_artifacts,
        ),
        ToolDefinition(
            name="cancel_qualification_job",
            description="Request cancellation of a running qualification job.",
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID returned by qualify_candidates."},
                },
                "required": ["job_id"],
                "additionalProperties": False,
            },
            execute=_tool_cancel_qualification_job,
            destructive=True,
        ),
        ToolDefinition(
            name="analyze_company_import",
            description=(
                "Analyze an ERP company workbook (XLSX) attached to the "
                "current chat session and stage it for review: companies, "
                "customers, suppliers, VAT/registration identifiers, "
                "domains, roles and firmographics. The analysis NEVER "
                "changes canonical business data — it produces an import "
                "batch with proposed changes, conflicts and a review URL; "
                "a human must review, approve and commit before anything "
                "is written. On a request to import companies from an "
                "attached workbook, call this tool. If profile selection "
                "is ambiguous the result says so — ask the user which "
                "profile to use instead of guessing. Never invent "
                "attachment ids. If a batch for the same workbook was "
                "already analyzed, report its status instead of "
                "re-analyzing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "attachment_id": {
                        "type": "string",
                        "description": "Attachment ID of the ERP workbook "
                                       "in the current session.",
                    },
                    "source_system": {
                        "type": "string",
                        "description": "Source system label for the "
                                       "workbook (e.g. 'erp').",
                    },
                    "profile": {
                        "type": "string",
                        "description": "Import profile: AUTO (default) or "
                                       "an explicit label such as "
                                       "ERP_CUSTOMER_EXPORT_V1.",
                    },
                    "default_country": {
                        "type": "string",
                        "description": "Optional default country (ISO "
                                       "code) for rows without one.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional import notes recorded "
                                       "with the batch.",
                    },
                },
                "required": ["attachment_id"],
                "additionalProperties": False,
            },
            execute=_tool_analyze_company_import,
        ),
        ToolDefinition(
            name="commit_company_import",
            description=(
                "Commit an APPROVED ERP import batch into the company "
                "database (transactional, idempotent). ONLY call this "
                "after the user EXPLICITLY asks to commit an approved "
                "import batch — never automatically after analysis, and "
                "never for a batch that is not APPROVED. The batch must "
                "have been analyzed with analyze_company_import and "
                "approved through the review workflow. Returns the "
                "reconciliation report of created/updated records."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "import_batch_id": {
                        "type": "string",
                        "description": "Import batch ID returned by "
                                       "analyze_company_import.",
                    },
                    "idempotency_key": {
                        "type": "string",
                        "description": "Optional idempotency key: "
                                       "recommitting the same approved "
                                       "batch with the same key returns "
                                       "the existing result.",
                    },
                },
                "required": ["import_batch_id"],
                "additionalProperties": False,
            },
            execute=_tool_commit_company_import,
            destructive=True,
        ),
    ]


async def _tool_analyze_company_import(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """analyze_company_import: stage an ERP workbook for review."""
    attachment_id = args.get("attachment_id", "")
    if not attachment_id or not ctx.allowed_attachment_ids:
        raise ToolExecutionError(
            "missing_attachment",
            "Attach the ERP workbook (XLSX) to the current chat session "
            "first.",
        )
    if attachment_id not in ctx.allowed_attachment_ids:
        raise ToolExecutionError(
            "identifier_not_allowed",
            "attachment_id is not an attachment of the current chat "
            "session.",
            http_status=403,
        )
    payload: Dict[str, Any] = {
        "session_id": ctx.session_id,
        "attachment_id": attachment_id,
        "source_system": args.get("source_system") or "erp",
        "profile": args.get("profile") or "AUTO",
    }
    if args.get("default_country"):
        payload["default_country"] = args["default_country"]
    if args.get("notes"):
        payload["notes"] = args["notes"]
    result = await _crm_request(
        "POST", "/api/v2/crm/imports/analyze", json=payload)

    if result.get("status") == "PROFILE_SELECTION_REQUIRED":
        selection = result.get("profile_selection") or {}
        result["chat_summary"] = (
            "The workbook's layout does not match a single import profile "
            "confidently "
            f"(reason: {selection.get('reason')}). Ask the user to choose "
            "one of: " + ", ".join(
                alt.get("profile", "?")
                for alt in (selection.get("alternatives") or [])[:4]
            ) + ", then analyze again with that profile."
        )
        return result

    counters = result.get("counters") or {}
    result["chat_summary"] = (
        "Workbook analyzed and staged for review — canonical company data "
        "is NOT changed until a human approves and commits the import. "
        f"Batch {result.get('import_batch_id')}: {counters.get('rows_received', 0)} rows "
        f"({counters.get('new_organizations_proposed', 0)} new organizations, "
        f"{counters.get('exact_matches', 0)} existing matches, "
        f"{counters.get('probable_or_ambiguous', 0)} needing review, "
        f"{counters.get('conflicts', 0)} conflicts). "
        f"Review URL: {result.get('review_url')}"
    )
    return result


async def _tool_commit_company_import(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """commit_company_import: commit an APPROVED import batch."""
    batch_id = (args.get("import_batch_id") or "").strip()
    if not batch_id:
        raise ToolExecutionError(
            "invalid_arguments",
            "import_batch_id is required.",
        )
    payload: Dict[str, Any] = {
        "actor_id": f"chat:{ctx.session_id}",
    }
    if args.get("idempotency_key"):
        payload["idempotency_key"] = args["idempotency_key"]
    result = await _crm_request(
        "POST", f"/api/v2/crm/imports/batches/{batch_id}/commit",
        json=payload)
    applied = result.get("applied") or {}
    recon = result.get("reconciliation_summary") or {}
    counters = recon.get("counters") or {}
    result["chat_summary"] = (
        f"Import batch {batch_id} committed"
        + (" (idempotent replay)" if result.get("idempotent_replay")
           else "")
        + f": {counters.get('created_organizations', 0)} organizations "
        "created, "
        + f"{counters.get('updated_organizations', 0)} updated, "
        + f"{counters.get('roles_added', 0)} roles, "
        + f"{counters.get('identifiers_added', 0)} identifiers. "
        f"Reconciliation: {result.get('reconciliation_url')}"
    )
    return result


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Registry of typed chat tools contributed by extensions."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return sorted(self._tools)

    def openai_schema(self, allowed: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """OpenAI function-calling `tools` array for the registered tools."""
        out = []
        for tool in self._tools.values():
            if allowed is not None and tool.name not in allowed:
                continue
            out.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            })
        return out


def build_default_tool_registry(allow_list: Optional[List[str]] = None) -> ToolRegistry:
    """Build the registry with the CRM Assistant tools (allow-list filtered)."""
    registry = ToolRegistry()
    for tool in build_crm_tools():
        if allow_list is None or tool.name in allow_list:
            registry.register(tool)
    return registry

