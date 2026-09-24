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
        ToolDefinition(
            name="create_campaign",
            description=(
                "Create a DRAFT outbound campaign (company-level "
                "campaign tracking). Validates campaign-code uniqueness "
                "within the tenant; the campaign is NOT activated — "
                "status stays DRAFT until a human promotes it. The "
                "human-facing identifier is the campaign_code (e.g. "
                "2026-CRA-It-SPS); campaign family, country, language "
                "and segment must be provided as explicit fields, never "
                "parsed out of the code."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "campaign_code": {
                        "type": "string",
                        "description": "Business campaign identifier "
                                       "(e.g. 2026-CRA-It-SPS).",
                    },
                    "name": {
                        "type": "string",
                        "description": "Human-readable campaign name.",
                    },
                    "campaign_family": {
                        "type": "string",
                        "description": "Campaign family (e.g. CRA).",
                    },
                    "country_code": {
                        "type": "string",
                        "description": "Country (ISO code, e.g. IT).",
                    },
                    "language_code": {
                        "type": "string",
                        "description": "Language (e.g. it).",
                    },
                    "segment_code": {
                        "type": "string",
                        "description": "Segment (e.g. SPS).",
                    },
                    "parent_campaign_id": {
                        "type": "string",
                        "description": "Optional parent campaign "
                                       "(code or ID).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description.",
                    },
                },
                "required": ["campaign_code", "name"],
                "additionalProperties": False,
            },
            execute=_tool_create_campaign,
        ),
        ToolDefinition(
            name="analyze_campaign_audience",
            description=(
                "Plan a campaign audience: evaluate every organization "
                "of the tenant against an approved selection policy and "
                "record one EXPLAINABLE decision per company "
                "(SELECT/EXCLUDE/SUPPRESS/REVIEW/DEFER). NEVER changes "
                "campaign membership; produces a selection run with a "
                "review URL. Requires an approved policy ID/name or an "
                "inline policy payload."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "campaign": {
                        "type": "string",
                        "description": "Campaign code or ID (e.g. "
                                       "2026-CRA-It-SPS).",
                    },
                    "policy_selector": {
                        "type": "string",
                        "description": "Approved selection policy (ID "
                                       "or name).",
                    },
                    "policy_payload": {
                        "type": "object",
                        "description": "Inline policy (creates a new "
                                       "DRAFT version); use only when "
                                       "the user supplied explicit "
                                       "policy values.",
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Optional planning parameters.",
                    },
                },
                "required": ["campaign"],
                "additionalProperties": False,
            },
            execute=_tool_analyze_campaign_audience,
        ),
        ToolDefinition(
            name="approve_campaign_audience",
            description=(
                "Approve a REVIEWED selection run (NEEDS_REVIEW -> "
                "APPROVED). Approval is refused by the server while "
                "blocking REVIEW decisions remain unresolved. This does "
                "NOT commit anything yet."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "selection_run_id": {
                        "type": "string",
                        "description": "Selection run ID returned by "
                                       "analyze_campaign_audience.",
                    },
                },
                "required": ["selection_run_id"],
                "additionalProperties": False,
            },
            execute=_tool_approve_campaign_audience,
        ),
        ToolDefinition(
            name="commit_campaign_audience",
            description=(
                "Commit an APPROVED selection run (transactional, "
                "idempotent). Creates or updates campaign-company "
                "associations; does NOT mark any company as addressed. "
                "ONLY call after the user EXPLICITLY asks to commit the "
                "approved audience."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "selection_run_id": {
                        "type": "string",
                        "description": "APPROVED selection run ID.",
                    },
                    "idempotency_key": {
                        "type": "string",
                        "description": "Optional idempotency key.",
                    },
                },
                "required": ["selection_run_id"],
                "additionalProperties": False,
            },
            execute=_tool_commit_campaign_audience,
            destructive=True,
        ),
        ToolDefinition(
            name="import_campaign_company_history",
            description=(
                "Analyze an attached campaign-history workbook (XLSX, "
                "profile CAMPAIGN_COMPANY_HISTORY_V1) and stage it for "
                "review: campaigns, company participation, explicit "
                "addressed confirmations and company-level outcomes. "
                "Presence in a campaign list NEVER implies the company "
                "was addressed. Requires review and approval before "
                "commit."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "attachment_id": {
                        "type": "string",
                        "description": "Attachment ID of the "
                                       "campaign-history workbook in "
                                       "the current session.",
                    },
                    "source_system": {
                        "type": "string",
                        "description": "Source system label (e.g. "
                                       "outreach tool name).",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional import notes.",
                    },
                },
                "required": ["attachment_id"],
                "additionalProperties": False,
            },
            execute=_tool_import_campaign_company_history,
        ),
        ToolDefinition(
            name="get_company_campaign_history",
            description=(
                "Return the company-level campaign history of one "
                "canonical organization: campaigns considered, "
                "selected, approved, exported and ADDRESSED, "
                "company-level responses/outcomes and next-eligibility "
                "projections. Never invents responses."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "organization_id": {
                        "type": "string",
                        "description": "Canonical organization ID.",
                    },
                },
                "required": ["organization_id"],
                "additionalProperties": False,
            },
            execute=_tool_get_company_campaign_history,
        ),
        ToolDefinition(
            name="mark_company_addressed",
            description=(
                "Record an explicit company-level ADDRESS_CONFIRMED "
                "event for one campaign. Requires campaign, canonical "
                "organization, addressed timestamp, source system, "
                "source record and a confirmation basis (external "
                "record, approved import or explicit human decision). "
                "Idempotent. Never use for mere selection or export "
                "status."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "campaign": {
                        "type": "string",
                        "description": "Campaign code or ID.",
                    },
                    "organization_id": {
                        "type": "string",
                        "description": "Canonical organization ID.",
                    },
                    "addressed_at": {
                        "type": "string",
                        "description": "Confirmed outreach timestamp "
                                       "(ISO-8601).",
                    },
                    "source_system": {
                        "type": "string",
                        "description": "Confirming source system.",
                    },
                    "source_record_id": {
                        "type": "string",
                        "description": "Confirming source reference.",
                    },
                    "confirmation_basis": {
                        "type": "string",
                        "description": "Why this counts as addressed "
                                       "(external record / approved "
                                       "import / human decision).",
                    },
                    "reason_text": {
                        "type": "string",
                        "description": "Optional free-text reason.",
                    },
                },
                "required": ["campaign", "organization_id",
                             "addressed_at", "source_system",
                             "source_record_id", "confirmation_basis"],
                "additionalProperties": False,
            },
            execute=_tool_mark_company_addressed,
        ),
        ToolDefinition(
            name="update_company_campaign_outcome",
            description=(
                "Record a company-level response or campaign outcome "
                "for one organization as a NEW append-only event and "
                "update the current projection. Values come from the "
                "response vocabulary (e.g. POSITIVE_RESPONSE, "
                "NO_RESPONSE, DO_NOT_CONTACT_REQUESTED) or the outcome "
                "vocabulary (e.g. CONVERTED, COMPLETED_POSITIVE)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "campaign": {
                        "type": "string",
                        "description": "Campaign code or ID.",
                    },
                    "organization_id": {
                        "type": "string",
                        "description": "Canonical organization ID.",
                    },
                    "response_status": {
                        "type": "string",
                        "description": "One of: UNKNOWN, NO_RESPONSE, "
                                       "RESPONDED, POSITIVE_RESPONSE, "
                                       "NEGATIVE_RESPONSE, "
                                       "NOT_INTERESTED, "
                                       "FOLLOW_UP_REQUESTED, "
                                       "MEETING_REQUESTED, "
                                       "OPPORTUNITY_CREATED, "
                                       "BOUNCED_OR_UNREACHABLE, "
                                       "DO_NOT_CONTACT_REQUESTED.",
                    },
                    "outcome": {
                        "type": "string",
                        "description": "One of: OPEN, "
                                       "COMPLETED_NO_RESPONSE, "
                                       "COMPLETED_NEGATIVE, "
                                       "COMPLETED_POSITIVE, CONVERTED, "
                                       "DISQUALIFIED, CANCELLED.",
                    },
                    "reason_text": {
                        "type": "string",
                        "description": "Optional free-text reason.",
                    },
                },
                "required": ["campaign", "organization_id"],
                "additionalProperties": False,
            },
            execute=_tool_update_company_campaign_outcome,
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
# Campaign tools (company-level campaign tracking milestone).  All
# campaign semantics are enforced server-side by the CRM extension;
# these handlers are thin, typed proxies.  The chat agent NEVER
# generates SQL.
# ---------------------------------------------------------------------------

async def _tool_create_campaign(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """create_campaign: create a DRAFT campaign."""
    code = (args.get("campaign_code") or "").strip()
    name = (args.get("name") or "").strip()
    if not code or not name:
        raise ToolExecutionError(
            "invalid_arguments",
            "campaign_code and name are required.")
    payload: Dict[str, Any] = {
        "campaign_code": code, "name": name,
        "actor_id": f"chat:{ctx.session_id}",
    }
    for key in ("description", "campaign_family", "parent_campaign_id",
                "country_code", "language_code", "offering_family_id",
                "segment_code", "planned_start_date",
                "planned_end_date", "source_system",
                "source_record_id"):
        if args.get(key):
            payload[key] = args[key]
    result = await _crm_request(
        "POST", "/api/v2/crm/campaigns", json=payload)
    result["chat_summary"] = (
        f"Campaign {result.get('campaign_code')} created with status "
        f"{result.get('status')}. It is NOT active yet; promote the "
        "status explicitly when planning starts."
    )
    return result


async def _tool_analyze_campaign_audience(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """analyze_campaign_audience: plan a campaign audience."""
    campaign = (args.get("campaign") or "").strip()
    if not campaign:
        raise ToolExecutionError(
            "invalid_arguments",
            "campaign (code or ID) is required.",
        )
    payload: Dict[str, Any] = {
        "actor_id": f"chat:{ctx.session_id}",
    }
    if args.get("policy_selector"):
        payload["policy_selector"] = args["policy_selector"]
    if args.get("policy_payload"):
        payload["policy_payload"] = args["policy_payload"]
    if args.get("parameters"):
        payload["parameters"] = args["parameters"]
    if args.get("row_limit"):
        payload["row_limit"] = args["row_limit"]
    result = await _crm_request(
        "POST", f"/api/v2/crm/campaigns/{campaign}/selection-runs",
        json=payload)
    result["chat_summary"] = (
        f"Selection run {result.get('selection_run_id')} created for "
        f"{result.get('campaign_code')}: considered "
        f"{result.get('considered')}, selected "
        f"{result.get('selected')}, excluded {result.get('excluded')}, "
        f"suppressed {result.get('suppressed')}, review "
        f"{result.get('review')}. Review URL: "
        f"{result.get('review_url')}"
    )
    return result


async def _tool_approve_campaign_audience(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """approve_campaign_audience: approve a reviewed selection run."""
    run_id = (args.get("selection_run_id") or "").strip()
    if not run_id:
        raise ToolExecutionError(
            "invalid_arguments",
            "selection_run_id is required.",
        )
    payload: Dict[str, Any] = {
        "actor_id": f"chat:{ctx.session_id}",
        "approved_by": f"chat:{ctx.session_id}",
    }
    result = await _crm_request(
        "POST", f"/api/v2/crm/campaigns/selection-runs/{run_id}/approve",
        json=payload)
    result["chat_summary"] = (
        f"Selection run {run_id} approved. It is NOT committed yet; "
        "ask the user before committing the audience."
    )
    return result


async def _tool_commit_campaign_audience(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """commit_campaign_audience: commit an APPROVED run."""
    run_id = (args.get("selection_run_id") or "").strip()
    if not run_id:
        raise ToolExecutionError(
            "invalid_arguments",
            "selection_run_id is required.",
        )
    payload: Dict[str, Any] = {
        "actor_id": f"chat:{ctx.session_id}",
    }
    if args.get("idempotency_key"):
        payload["idempotency_key"] = args["idempotency_key"]
    result = await _crm_request(
        "POST", f"/api/v2/crm/campaigns/selection-runs/{run_id}/commit",
        json=payload)
    result["chat_summary"] = (
        f"Selection run {run_id} committed: "
        f"{result.get('memberships_created', 0)} memberships created, "
        f"{result.get('memberships_updated', 0)} updated, "
        f"{result.get('events_appended', 0)} events appended. "
        "Nobody was marked addressed by the commit."
    )
    return result


async def _tool_import_campaign_company_history(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """import_campaign_company_history: stage a history workbook."""
    attachment_id = args.get("attachment_id", "")
    if not attachment_id or not ctx.allowed_attachment_ids:
        raise ToolExecutionError(
            "missing_attachment",
            "Attach the campaign-history workbook (XLSX) to the "
            "current chat session first.",
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
        "source_system": (args.get("source_system")
                          or "campaign_history"),
        "actor_id": f"chat:{ctx.session_id}",
    }
    if args.get("notes"):
        payload["notes"] = args["notes"]
    if args.get("row_limit"):
        payload["row_limit"] = args["row_limit"]
    result = await _crm_request(
        "POST", "/api/v2/crm/campaigns/import-history-attachment",
        json=payload)
    result["chat_summary"] = (
        f"Campaign-history workbook staged (batch "
        f"{result.get('import_batch_id')}): "
        f"{(result.get('counters') or {}).get('rows_received', 0)} rows. "
        "Presence in a campaign list NEVER means a company was "
        "addressed — only an explicit confirmation does. Review URL: "
        f"{result.get('review_url')}"
    )
    return result


async def _tool_get_company_campaign_history(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """get_company_campaign_history: participation + outcomes."""
    organization_id = (args.get("organization_id") or "").strip()
    if not organization_id:
        raise ToolExecutionError(
            "invalid_arguments",
            "organization_id (canonical) is required.",
        )
    result = await _crm_request(
        "GET",
        f"/api/v2/crm/campaigns/organizations/{organization_id}/history")
    campaigns_rows = result.get("campaigns") or []
    addressed_count = sum(
        1 for c in campaigns_rows
        if any(e.get("event_type") == "ADDRESS_CONFIRMED"
               for e in (c.get("events") or [])))
    result["chat_summary"] = (
        f"{len(campaigns_rows)} campaign(s) on record for this company; "
        f"explicitly addressed in {addressed_count}. Selected/approved "
        "status alone never means addressed."
    )
    return result


async def _tool_mark_company_addressed(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """mark_company_addressed: explicit ADDRESS_CONFIRMED event."""
    campaign = (args.get("campaign") or "").strip()
    organization_id = (args.get("organization_id") or "").strip()
    addressed_at = (args.get("addressed_at") or "").strip()
    source_system = (args.get("source_system") or "").strip()
    source_record_id = (args.get("source_record_id") or "").strip()
    basis = (args.get("confirmation_basis") or "").strip()
    required = (
        ("campaign", campaign), ("organization_id", organization_id),
        ("addressed_at", addressed_at),
        ("source_system", source_system),
        ("source_record_id", source_record_id),
        ("confirmation_basis", basis))
    missing = [name for name, value in required if not value]
    if missing:
        raise ToolExecutionError(
            "invalid_arguments",
            "campaign, organization_id, addressed_at, source_system, "
            "source_record_id and confirmation_basis are all required.",
        )
    payload: Dict[str, Any] = {
        "actor_id": f"chat:{ctx.session_id}",
        "addressed_at": addressed_at,
        "source_system": source_system,
        "source_record_id": source_record_id,
        "confirmation_basis": basis,
    }
    if args.get("reason_text"):
        payload["reason_text"] = args["reason_text"]
    result = await _crm_request(
        "POST", f"/api/v2/crm/campaigns/{campaign}/companies/"
                f"{organization_id}/addressed",
        json=payload)
    result["chat_summary"] = (
        "ADDRESS_CONFIRMED event recorded; the company is now marked "
        "addressed for this campaign."
    )
    return result


async def _tool_update_company_campaign_outcome(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """update_company_campaign_outcome: append outcome event."""
    campaign = (args.get("campaign") or "").strip()
    organization_id = (args.get("organization_id") or "").strip()
    if not campaign or not organization_id:
        raise ToolExecutionError(
            "invalid_arguments",
            "campaign and organization_id are required.",
        )
    if not args.get("response_status") and not args.get("outcome"):
        raise ToolExecutionError(
            "invalid_arguments",
            "response_status or outcome is required.",
        )
    payload: Dict[str, Any] = {
        "actor_id": f"chat:{ctx.session_id}",
    }
    for key in ("response_status", "outcome", "reason_text",
                "source_system", "source_record_id", "correlation_id"):
        if args.get(key):
            payload[key] = args[key]
    result = await _crm_request(
        "POST", f"/api/v2/crm/campaigns/{campaign}/companies/"
                f"{organization_id}/outcome",
        json=payload)
    result["chat_summary"] = (
        "Company-level outcome recorded as a new append-only event "
        "and the current projection was updated."
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

