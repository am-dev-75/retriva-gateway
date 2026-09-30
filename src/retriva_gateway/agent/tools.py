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
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Dict, List, Optional

from loguru import logger

from retriva_gateway.config import settings
from retriva_gateway.core.client import core_client
from retriva_gateway.core.context import get_correlation_id


def _public_url(path: str) -> str:
    """Absolute, browser-reachable URL for a gateway-served path.

    The import review/reconciliation pages are proxied by the gateway
    (``/api/v2/crm/imports/*`` passthrough), so prefixing the public
    gateway origin yields a URL a human can simply click.
    """
    base = (getattr(settings, "GATEWAY_PUBLIC_URL", "") or "").rstrip("/")
    return f"{base}{path}"


def _public_review_url(review_url: Optional[str]) -> str:
    """Absolute review URL for chat presentation.

    The server returns a root-relative path; if a future server already
    returns an absolute URL it is passed through unchanged.
    """
    url = review_url or ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return _public_url(url)


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
        # -----------------------------------------------------------------
        # ACP workflow tools (Spec 020 / ADR-023).  PostgreSQL business
        # workflow over the accepted /api/v2/crm/acp/ API — never RAG,
        # never the KB/Qdrant/tag/SQLite, never model-generated SQL.
        # -----------------------------------------------------------------
        ToolDefinition(
            name="propose_acp_cohort",
            description=(
                "Start the PostgreSQL ACP workflow: propose a reference "
                "cohort of customer companies from the PostgreSQL "
                "Company Intelligence Database (DRAFT only). Call on "
                "requests to extrapolate, create, derive or rebuild the "
                "Average Customer Profile when no reviewed cohort "
                "version was specified. The initial request authorizes "
                "PROPOSAL ONLY: never approves, never generates, never "
                "activates. Returns counts, warnings, blocking issues "
                "and the review URL. NOT a knowledge-base question — "
                "do not fall back to RAG answers."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short cohort name, e.g. "
                                       "'Active customers'.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional human description.",
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            execute=_tool_propose_acp_cohort,
        ),
        ToolDefinition(
            name="get_acp_cohort",
            description=(
                "Read one ACP reference cohort (status, current "
                "version, counts, snapshot hash when approved). "
                "Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "cohort_id": {
                        "type": "string",
                        "description": "Cohort ID (acpc_...).",
                    },
                },
                "required": ["cohort_id"],
                "additionalProperties": False,
            },
            execute=_tool_get_acp_cohort,
        ),
        ToolDefinition(
            name="list_acp_cohort_members",
            description=(
                "List the members of an ACP cohort version with their "
                "decision states (include/exclude/pending/outlier/"
                "insufficient-data), minimum review-level fields only. "
                "Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "cohort_id": {
                        "type": "string",
                        "description": "Cohort ID (acpc_...).",
                    },
                    "version_number": {
                        "type": "integer",
                        "description": "Optional version number; the "
                                       "current version when omitted.",
                    },
                },
                "required": ["cohort_id"],
                "additionalProperties": False,
            },
            execute=_tool_list_acp_cohort_members,
        ),
        ToolDefinition(
            name="update_acp_cohort_member",
            description=(
                "Record ONE reviewed cohort membership decision "
                "(include, exclude, weight, outlier, insufficient-data, "
                "or manual removal). Use ONLY on explicit user review "
                "decisions; decision history and audit are preserved; "
                "this never approves the cohort."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "cohort_id": {
                        "type": "string",
                        "description": "Cohort ID (acpc_...).",
                    },
                    "organization_id": {
                        "type": "string",
                        "description": "Canonical organization ID of "
                                       "the member.",
                    },
                    "decision": {
                        "type": "string",
                        "enum": ["INCLUDED", "EXCLUDED",
                                 "PENDING_REVIEW", "OUTLIER",
                                 "INSUFFICIENT_DATA"],
                        "description": "The reviewed decision.",
                    },
                    "weight": {
                        "type": "number",
                        "description": "Weight (only meaningful for "
                                       "INCLUDED).",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Short decision reason (for "
                                       "exclusion/outlier/insufficient).",
                    },
                    "reviewer_comment": {
                        "type": "string",
                        "description": "Optional reviewer comment.",
                    },
                    "remove": {
                        "type": "boolean",
                        "description": "true = manual removal "
                                       "(MANUAL_REMOVAL provenance).",
                    },
                },
                "required": ["cohort_id", "organization_id", "decision"],
                "additionalProperties": False,
            },
            execute=_tool_update_acp_cohort_member,
        ),
        ToolDefinition(
            name="submit_acp_cohort_for_review",
            description=(
                "Report the cohort review lifecycle state. In the "
                "accepted workflow the version is submitted implicitly "
                "when approved; this tool returns the lifecycle "
                "guidance and the review URL. Does not approve."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "cohort_id": {
                        "type": "string",
                        "description": "Cohort ID (acpc_...).",
                    },
                    "version_number": {
                        "type": "integer",
                        "description": "Optional version number.",
                    },
                },
                "required": ["cohort_id"],
                "additionalProperties": False,
            },
            execute=_tool_submit_acp_cohort_for_review,
        ),
        ToolDefinition(
            name="approve_acp_cohort",
            description=(
                "Approve and freeze the reviewed cohort version into an "
                "immutable snapshot (hash verified upstream). Call ONLY "
                "when the user EXPLICITLY requests cohort approval. "
                "Refuses while membership decisions are unresolved. "
                "Never generates an ACP and never activates anything."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "cohort_id": {
                        "type": "string",
                        "description": "Cohort ID (acpc_...).",
                    },
                    "version_number": {
                        "type": "integer",
                        "description": "Optional version number; the "
                                       "open version otherwise.",
                    },
                    "comment": {
                        "type": "string",
                        "description": "Optional approval comment.",
                    },
                },
                "required": ["cohort_id"],
                "additionalProperties": False,
            },
            execute=_tool_approve_acp_cohort,
            destructive=True,
        ),
        ToolDefinition(
            name="generate_acp",
            description=(
                "Generate a review-ready ACP draft from an APPROVED "
                "cohort version (deterministic induction over frozen, "
                "snapshot-hash-verified inputs). Call ONLY on an "
                "explicit generation request. Never approves and never "
                "activates; the active ACP stays unchanged."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "acp_cohort_version_id": {
                        "type": "string",
                        "description": "APPROVED cohort version ID "
                                       "(acpcv_...).",
                    },
                    "idempotency_key": {
                        "type": "string",
                        "description": "Optional idempotency key: "
                                       "re-running with the same key "
                                       "returns the recorded run.",
                    },
                },
                "required": ["acp_cohort_version_id"],
                "additionalProperties": False,
            },
            execute=_tool_generate_acp,
        ),
        ToolDefinition(
            name="get_acp_generation_run",
            description=(
                "Read one ACP generation run (status, snapshot hash, "
                "result ACP version, contribution counters). "
                "Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "generation_run_id": {
                        "type": "string",
                        "description": "Generation run ID (acpr_...).",
                    },
                },
                "required": ["generation_run_id"],
                "additionalProperties": False,
            },
            execute=_tool_get_acp_generation_run,
        ),
        ToolDefinition(
            name="get_acp_version",
            description=(
                "Read one ACP version (status, validation, review "
                "readiness, payload and snapshot hashes). Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "acp_id": {
                        "type": "string",
                        "description": "Logical ACP ID (icp_.../acp_...).",
                    },
                    "version_number": {
                        "type": "integer",
                        "description": "Version number.",
                    },
                },
                "required": ["acp_id", "version_number"],
                "additionalProperties": False,
            },
            execute=_tool_get_acp_version,
        ),
        ToolDefinition(
            name="submit_acp_for_review",
            description=(
                "Submit a generated ACP draft for review (DRAFT -> "
                "REVIEW_READY; the payload stays byte-identical). "
                "Never generates, never scores, never activates."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "acp_id": {
                        "type": "string",
                        "description": "Logical ACP ID.",
                    },
                    "version_number": {
                        "type": "integer",
                        "description": "Version number.",
                    },
                },
                "required": ["acp_id", "version_number"],
                "additionalProperties": False,
            },
            execute=_tool_submit_acp_for_review,
        ),
        ToolDefinition(
            name="approve_acp",
            description=(
                "Approve the complete ACP version (immutable approval "
                "record). Call ONLY when the user EXPLICITLY requests "
                "ACP approval. Never activates; the currently active "
                "ACP stays unchanged."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "acp_id": {
                        "type": "string",
                        "description": "Logical ACP ID.",
                    },
                    "version_number": {
                        "type": "integer",
                        "description": "Version number.",
                    },
                    "comments": {
                        "type": "string",
                        "description": "Optional review comments.",
                    },
                },
                "required": ["acp_id", "version_number"],
                "additionalProperties": False,
            },
            execute=_tool_approve_acp,
            destructive=True,
        ),
        ToolDefinition(
            name="activate_acp",
            description=(
                "ACTIVATE an approved ACP version (transactional, "
                "exactly one active ACP per tenant, ledger + audit). "
                "Call ONLY on an explicit activation request — never "
                "infer activation from create/generate/extrapolate/"
                "review/approve wording. Fails closed if another ACP "
                "is already active."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "acp_id": {
                        "type": "string",
                        "description": "Logical ACP ID.",
                    },
                    "version_number": {
                        "type": "integer",
                        "description": "Version number.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional activation reason.",
                    },
                },
                "required": ["acp_id", "version_number"],
                "additionalProperties": False,
            },
            execute=_tool_activate_acp,
            destructive=True,
        ),
        ToolDefinition(
            name="rollback_acp_activation",
            description=(
                "Roll back an ACP activation through the activation "
                "ledger (restores the previously active version; a new "
                "ledger operation; history is never rewritten). Call "
                "ONLY on an explicit rollback request."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "acp_id": {
                        "type": "string",
                        "description": "Logical ACP ID to restore.",
                    },
                    "version_number": {
                        "type": "integer",
                        "description": "Version number to restore.",
                    },
                    "rollback_of_activation_id": {
                        "type": "string",
                        "description": "Activation ID being rolled "
                                       "back (from activate output).",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional rollback reason.",
                    },
                },
                "required": ["acp_id", "version_number"],
                "additionalProperties": False,
            },
            execute=_tool_rollback_acp_activation,
            destructive=True,
        ),
        ToolDefinition(
            name="get_active_acp",
            description=(
                "Resolve the tenant's currently ACTIVE ACP (identity, "
                "status, hashes; no payload content). Read-only. "
                "The active ACP is comparison data only — never source "
                "evidence for a new cohort."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            execute=_tool_get_active_acp,
        ),
        ToolDefinition(
            name="get_acp_lineage",
            description=(
                "Read the lineage of one ACP version (cohort, snapshot "
                "hash, generation run, approvals, activation ledger) — "
                "opaque IDs and hashes only. Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "acp_id": {
                        "type": "string",
                        "description": "Logical ACP ID.",
                    },
                    "version_number": {
                        "type": "integer",
                        "description": "Version number.",
                    },
                },
                "required": ["acp_id", "version_number"],
                "additionalProperties": False,
            },
            execute=_tool_get_acp_lineage,
        ),
        # -------------------------------------------------------------
        # Evidence enrichment (Spec 021 / ADR-024): generation
        # prerequisites visibility + permission-gated enrichment via the
        # qualification research machinery. UNVERIFIED observations;
        # acceptance is a separate explicit step. ACP generation stays
        # deterministic and provider-free.
        # -------------------------------------------------------------
        ToolDefinition(
            name="get_acp_generation_prerequisites",
            description=(
                "Read the live generation prerequisites of one cohort "
                "version: per-member evidence status (frozen vs live), "
                "missing policy fields and stale fields — i.e. which "
                "customer companies are NOT yet enriched. Use when "
                "generation reported incomplete evidence, or when the "
                "user asks whether the cohort companies are enriched. "
                "Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "acp_cohort_version_id": {
                        "type": "string",
                        "description": "Cohort version ID (cohver_...).",
                    },
                },
                "required": ["acp_cohort_version_id"],
                "additionalProperties": False,
            },
            execute=_tool_get_acp_generation_prerequisites,
        ),
        ToolDefinition(
            name="enrich_acp_cohort_evidence",
            description=(
                "Start the evidence-enrichment job for one cohort "
                "version's members (default: every non-excluded "
                "member; optional explicit subset). Uses the same "
                "web-research machinery as new-lead qualification to "
                "fill the missing policy fields; researched values land "
                "as UNVERIFIED observations. Call ONLY on the user's "
                "explicit approval to enrich; never fabricates evidence "
                "and NEVER accepts the results (acceptance is a "
                "separate explicit step)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "acp_cohort_version_id": {
                        "type": "string",
                        "description": "Cohort version ID (cohver_...).",
                    },
                    "organization_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional subset of member "
                                       "organization IDs to enrich.",
                    },
                },
                "required": ["acp_cohort_version_id"],
                "additionalProperties": False,
            },
            execute=_tool_enrich_acp_cohort_evidence,
            destructive=True,
        ),
        ToolDefinition(
            name="get_acp_evidence_enrichment_job",
            description=(
                "Read one evidence-enrichment job: state, per-company "
                "resolved fields (values, source domain, confidence, "
                "observation IDs) and unresolved fields. Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Enrichment job ID (ench_...).",
                    },
                },
                "required": ["job_id"],
                "additionalProperties": False,
            },
            execute=_tool_get_acp_evidence_enrichment_job,
        ),
        ToolDefinition(
            name="accept_acp_enrichment_evidence",
            description=(
                "Accept the evidence observations recorded by one "
                "completed enrichment job (audited; supersedes the "
                "previous accepted value per field). Call ONLY on the "
                "user's SEPARATE explicit approval AFTER presenting the "
                "per-company field summary. Never fabricates and never "
                "generates."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Enrichment job ID (ench_...).",
                    },
                    "observation_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional subset of the job's "
                                       "observation IDs to accept.",
                    },
                },
                "required": ["job_id"],
                "additionalProperties": False,
            },
            execute=_tool_accept_acp_enrichment_evidence,
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
        f"[Open the review page in a new tab]"
        f"({_public_review_url(result.get('review_url'))})"
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
        f"[Open the reconciliation report in a new tab]"
        f"({_public_review_url(result.get('reconciliation_url'))})"
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
        f"{result.get('review')}. "
        f"[Open the audience review page in a new tab]"
        f"({result.get('review_url')})"
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
        "addressed — only an explicit confirmation does. "
        f"[Open the history review page in a new tab]"
        f"({result.get('review_url')})"
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
# ACP workflow tools (Spec 020 / ADR-023): narrow, typed, authorized
# proxies over the accepted PostgreSQL ACP API (/api/v2/crm/acp/...).
# The Gateway holds NO eligibility, identity-resolution, hashing,
# induction, approval, activation, permission, or audit logic.  The body
# actor_id is audit attribution only; tenant context is resolved
# server-side and is never a tool argument; the model never generates
# SQL or arbitrary internal HTTP requests.
# ---------------------------------------------------------------------------

_ACP_BASE = "/api/v2/crm/acp"
ACP_COHORT_CONSOLE_PATH = f"{_ACP_BASE}/cohorts/console"
ACP_CONSOLE_PATH = f"{_ACP_BASE}/acps/console"

#: Upstream accepted typed codes -> governing tool error taxonomy
#: (Spec 020 "Error handling").  `upstream_code` is preserved for audit.
_ACP_ERROR_CODE_MAP = {
    "ACP_PERMISSION_DENIED": "permission_denied",
    "ACP_TENANT_CONTEXT_MISSING": "tenant_context_missing",
    "ACP_NO_ACTIVE": "no_active_acp",
    "ACP_MULTIPLE_ACTIVE": "invalid_state",
    "ACP_INVALID_POLICY": "invalid_policy",
    "ACP_NO_APPROVED_COHORT": "approval_missing",
    "ACP_SNAPSHOT_INVALID": "invalid_snapshot_hash",
    "ACP_GENERATION_PREREQUISITES_INCOMPLETE": "incomplete_evidence",
    "ACP_COHORT_EMPTY": "incomplete_evidence",
    "WEB_RESEARCH_NOT_READY": "research_not_ready",
    "ACP_ENRICHMENT_TARGETS_INVALID": "invalid_state",
    "ACP_ACTIVE_CONFLICT": "activation_conflict",
    "IDEMPOTENCY_CONFLICT": "activation_conflict",
    "INVALID_TRANSITION": "review_not_ready",
    "NOT_FOUND": "not_found",
    "NOOP": "invalid_state",
    "ACP_INVALID": "invalid_state",
    "ACP_INVALID_STATE": "invalid_state",
}


def _acp_error_body(status_code: int,
                    body: Dict[str, Any]) -> Dict[str, Any]:
    """Typed, safe tool-error projection of an upstream ACP error."""
    upstream = str(body.get("reason_code") or body.get("code") or "")
    code = _ACP_ERROR_CODE_MAP.get(upstream, "invalid_state")
    if status_code == 503:
        code = "postgres_unavailable"
    return {
        "code": code,
        "message": str(body.get("detail")
                       or f"ACP API returned {status_code}")[:500],
        "upstream_code": upstream,
    }


async def _acp_call(method: str, path: str,
                    json_payload: Optional[Dict[str, Any]] = None,
                    ) -> Dict[str, Any]:
    """Call the accepted CRM ACP API.  Typed domain errors become typed
    tool failures; the tool layer never recovers by falling back."""
    import httpx
    try:
        resp = await core_client._request(
            method, core_client.ingestion_base_url, path,
            json=json_payload)
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
        except Exception:  # noqa: BLE001 - non-JSON upstream error body
            body = {}
        if not isinstance(body, dict):
            body = {"detail": str(body)[:300]}
        return {"error": _acp_error_body(exc.response.status_code, body)}
    except httpx.RequestError:
        return {"error": {
            "code": "postgres_unavailable",
            "message": "the ACP API is unreachable (transport error)",
            "upstream_code": "TRANSPORT",
        }}
    return resp.json()


def _acp_actor(ctx: ToolContext) -> str:
    """Attribution-only body actor (audit lineage; never a permission
    authority — authorization rides the gateway-injected trusted
    principal header)."""
    return f"chat:{ctx.session_id}"


def _acp_arg_str(args: Dict[str, Any], key: str, label: str) -> str:
    value = str(args.get(key) or "").strip()
    if not value:
        raise ToolExecutionError("invalid_arguments",
                                 f"{label} is required.")
    return value


# Opaque upstream identifiers follow "<prefix>_<url-safe-suffix>" (the
# accepted `job_` discipline).  Model-supplied ids are interpolated into
# proxied paths, so anything else (path separators, crafted routes) is
# rejected before it can rewrite the upstream route (review fix 16:
# containment parity with the qualification tools).
_ACP_ID_RE = re.compile(r"^[A-Za-z0-9]{2,20}_[A-Za-z0-9\-]{1,64}$")


def _acp_arg_id(args: Dict[str, Any], key: str, label: str) -> str:
    value = _acp_arg_str(args, key, label)
    if not _ACP_ID_RE.match(value):
        raise ToolExecutionError(
            "invalid_arguments",
            f"{label} must be an opaque identifier (prefix_suffix); "
            f"got {value[:40]!r}.")
    return value


def _acp_error(code: str, message: str, **extra: Any) -> Dict[str, Any]:
    error = {"code": code, "message": message}
    error.update(extra)
    return {"error": error}


def _member_min_view(member: Dict[str, Any]) -> Dict[str, Any]:
    """Minimum review-level member projection (no evidence bodies)."""
    return {
        "organization_id": member.get("organization_id"),
        "canonical_legal_name": member.get("canonical_legal_name"),
        "country_code": member.get("country_code"),
        "decision": member.get("decision"),
        "weight": member.get("weight"),
        "reason_code": (member.get("exclusion_reason_code")
                        or member.get("reason_code")),
        "identity_resolution_status":
            member.get("identity_resolution_status"),
        "evidence_status": member.get("evidence_status"),
        "freshness_status": member.get("freshness_status"),
        "provenance": member.get("provenance"),
    }


async def _acp_cohort_version_detail(cohort_id: str,
                                     version_number: Optional[int],
                                     ) -> Dict[str, Any]:
    """GET the cohort version (current when no version number given);
    returns the raw API projection or an error dict."""
    if version_number is None:
        cohort = await _acp_call("GET", f"{_ACP_BASE}/cohorts/{cohort_id}")
        if "error" in cohort:
            return cohort
        version_number = cohort.get("current_version")
        if version_number is None:
            return _acp_error(
                "review_not_ready",
                "the cohort has no versions yet; propose one first")
    return await _acp_call(
        "GET", f"{_ACP_BASE}/cohorts/{cohort_id}/versions/{version_number}")


async def _tool_propose_acp_cohort(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """propose_acp_cohort: PROPOSE_ACP_COHORT — create a DRAFT
    reference-cohort proposal from PostgreSQL Company Intelligence
    (never approve, never generate)."""
    name = _acp_arg_str(args, "name", "cohort name")
    payload: Dict[str, Any] = {
        "name": name, "actor_id": _acp_actor(ctx)}
    if args.get("description"):
        payload["description"] = str(args["description"])[:500]
    result = await _acp_call("POST", f"{_ACP_BASE}/cohorts", payload)
    if "error" in result:
        return result
    cohort_id = result.get("acp_cohort_id")
    version_number = result.get("current_version")
    counts = result.get("counts") or {}
    proposal_counts = result.get("proposal_counts") or {}
    considered = int(proposal_counts.get("considered") or 0)
    detail = None
    if cohort_id and version_number:
        detail = await _acp_cohort_version_detail(cohort_id, version_number)
        if "error" in detail:
            detail = None
    members = ((detail or {}).get("members") or [])
    identity_review = [
        m for m in members
        if str(m.get("identity_resolution_status") or "RESOLVED")
        != "RESOLVED"]
    pending = int(counts.get("pending_review") or 0)
    cap_skipped = int(proposal_counts.get("cap_skipped") or 0)
    stale = len([
        m for m in members
        if str(m.get("freshness_status") or "").upper() == "STALE"])
    warnings: List[Dict[str, Any]] = []
    if cap_skipped:
        warnings.append({
            "code": "CAP_SKIPPED", "count": cap_skipped,
            "message": "organizations omitted by the deterministic "
                       "policy cap; omission is not a business "
                       "exclusion"})
    insufficient = int(counts.get("insufficient_data") or 0)
    if insufficient:
        warnings.append({
            "code": "INSUFFICIENT_DATA", "count": insufficient,
            "message": "members lack the minimum accepted evidence; an "
                       "evidence refresh is a separate explicit "
                       "workflow (never automatic)"})
    if stale:
        warnings.append({
            "code": "STALE_EVIDENCE", "count": stale,
            "message": "accepted observations are older than the "
                       "policy freshness window"})
    blocking_issues: List[Dict[str, Any]] = []
    if identity_review:
        blocking_issues.append({
            "code": "IDENTITY_REVIEW_REQUIRED",
            "count": len(identity_review),
            "organization_ids": [
                m.get("organization_id") for m in identity_review][:20]})
    if pending:
        blocking_issues.append({
            "code": "PENDING_REVIEW", "count": pending,
            "message": "membership decisions require human review "
                       "before approval"})
    if considered == 0 and not members:
        return _acp_error(
            "no_eligible_customers",
            "no canonical organizations satisfied the accepted "
            "eligibility policy; nothing was proposed",
            cohort_id=cohort_id,
            cohort_version_id=(detail or {}).get("acp_cohort_version_id"))
    out = {
        "cohort_id": cohort_id,
        "cohort_version_id": (detail or {}).get("acp_cohort_version_id"),
        "status": result.get("status"),
        "policy_id": result.get("policy_version"),
        "policy_version": result.get("policy_version"),
        "considered_count": considered,
        "pending_review_count": pending,
        "excluded_count": int(counts.get("excluded") or 0),
        "insufficient_data_count": insufficient,
        "outlier_candidate_count": int(counts.get("outlier") or 0),
        "identity_review_count": len(identity_review),
        "included_count": int(counts.get("included") or 0),
        "warnings": warnings,
        "blocking_issues": blocking_issues,
        "review_url": _public_review_url(ACP_COHORT_CONSOLE_PATH),
    }
    out["chat_summary"] = (
        f"Draft reference-cohort proposal created: cohort "
        f"{cohort_id} version {version_number} "
        f"({out['pending_review_count']} pending review, "
        f"{out['excluded_count']} excluded by policy, "
        f"{out['insufficient_data_count']} insufficient data). "
        f"Review it at {out['review_url']} — nothing has been "
        f"approved, generated, or activated.")
    return out


async def _tool_get_acp_cohort(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """get_acp_cohort: read one cohort (bounded view)."""
    cohort_id = _acp_arg_id(args, "cohort_id", "cohort_id")
    result = await _acp_call("GET", f"{_ACP_BASE}/cohorts/{cohort_id}")
    if "error" in result:
        return result
    result["review_url"] = _public_review_url(ACP_COHORT_CONSOLE_PATH)
    result["chat_summary"] = (
        f"Cohort {cohort_id}: status {result.get('status')}, "
        f"version {result.get('current_version')} "
        f"({result.get('version_status')}).")
    return result


async def _tool_list_acp_cohort_members(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """list_acp_cohort_members: members + decision states (minimum
    review-level fields only)."""
    cohort_id = _acp_arg_id(args, "cohort_id", "cohort_id")
    version_number = args.get("version_number")
    detail = await _acp_cohort_version_detail(cohort_id, version_number)
    if "error" in detail:
        return detail
    members = [_member_min_view(m)
               for m in (detail.get("members") or [])]
    return {
        "cohort_id": cohort_id,
        "acp_cohort_version_id": detail.get("acp_cohort_version_id"),
        "version": detail.get("version"),
        "status": detail.get("status"),
        "member_count_included": detail.get("member_count_included"),
        "member_count_excluded": detail.get("member_count_excluded"),
        "member_count_pending_review":
            detail.get("member_count_pending_review"),
        "member_count_outlier": detail.get("member_count_outlier"),
        "member_count_insufficient":
            detail.get("member_count_insufficient"),
        "snapshot_hash": detail.get("snapshot_hash"),
        "members": members,
        "review_url": _public_review_url(ACP_COHORT_CONSOLE_PATH),
        "chat_summary": (
            f"Cohort version {detail.get('version')} "
            f"({detail.get('status')}): {len(members)} members "
            f"listed with their decision states."),
    }


async def _tool_update_acp_cohort_member(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """update_acp_cohort_member: REVIEW_ACP_COHORT — record one
    reviewed membership decision (history and audit preserved
    upstream; never approves)."""
    cohort_id = _acp_arg_id(args, "cohort_id", "cohort_id")
    organization_id = _acp_arg_id(args, "organization_id",
                                   "organization_id")
    decision = _acp_arg_str(args, "decision", "decision")
    allowed = {"INCLUDED", "EXCLUDED", "PENDING_REVIEW", "OUTLIER",
               "INSUFFICIENT_DATA"}
    if decision not in allowed:
        raise ToolExecutionError(
            "invalid_arguments",
            f"decision must be one of {', '.join(sorted(allowed))}")
    payload: Dict[str, Any] = {
        "decision": decision, "actor_id": _acp_actor(ctx)}
    if decision == "INCLUDED" and args.get("weight") is not None:
        payload["weight"] = args["weight"]
    if args.get("reason"):
        payload["reason"] = str(args["reason"])[:500]
    if args.get("reviewer_comment"):
        payload["reviewer_comment"] = str(args["reviewer_comment"])[:500]
    if args.get("remove"):
        payload["remove"] = True
    result = await _acp_call(
        "POST", f"{_ACP_BASE}/cohorts/{cohort_id}/members/"
                f"{organization_id}/decision", payload)
    if "error" in result:
        return result
    result["chat_summary"] = (
        f"Decision {decision} recorded for organization "
        f"{organization_id} (decision history and audit preserved). "
        f"The cohort version is NOT approved by this action.")
    return result


async def _tool_submit_acp_cohort_for_review(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """submit_acp_cohort_for_review: lifecycle guidance per the
    accepted workflow (the version is submitted implicitly upon
    approval; ADR-023 decision 6b/OQ2)."""
    cohort_id = _acp_arg_id(args, "cohort_id", "cohort_id")
    version_number = args.get("version_number")
    detail = await _acp_cohort_version_detail(cohort_id, version_number)
    if "error" in detail:
        return detail
    return {
        "info_code": "ACP_LIFECYCLE_INFO",
        "cohort_id": cohort_id,
        "acp_cohort_version_id": detail.get("acp_cohort_version_id"),
        "version_status": detail.get("status"),
        "message": "In the accepted ACP workflow a cohort version is "
                   "submitted for review implicitly when it is "
                   "approved. Apply review decisions first "
                   "(update_acp_cohort_member), then explicitly ask to "
                   "approve the cohort.",
        "review_url": _public_review_url(ACP_COHORT_CONSOLE_PATH),
        "chat_summary": (
            "Cohort submission happens implicitly at approval in the "
            "accepted workflow; review decisions come first."),
    }


async def _tool_approve_acp_cohort(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """approve_acp_cohort: APPROVE_ACP_COHORT — pre-check unresolved
    decisions, then approve the open version (immutable snapshot +
    verified hash upstream).  Never generates."""
    cohort_id = _acp_arg_id(args, "cohort_id", "cohort_id")
    detail = await _acp_cohort_version_detail(
        cohort_id, args.get("version_number"))
    if "error" in detail:
        return detail
    members = detail.get("members") or []
    pending = [m for m in members
               if m.get("decision") == "PENDING_REVIEW"]
    identity = [m for m in members
                if str(m.get("identity_resolution_status") or "RESOLVED")
                != "RESOLVED"]
    if pending or identity:
        return _acp_error(
            "unresolved_decisions",
            "the cohort version still has unresolved membership "
            "decisions; resolve them through review before approval",
            pending_review_count=len(pending),
            identity_review_count=len(identity),
            review_url=_public_review_url(ACP_COHORT_CONSOLE_PATH))
    payload: Dict[str, Any] = {"actor_id": _acp_actor(ctx)}
    if args.get("comment"):
        payload["comment"] = str(args["comment"])[:500]
    result = await _acp_call(
        "POST", f"{_ACP_BASE}/cohorts/{cohort_id}/approve", payload)
    if "error" in result:
        return result
    result["review_url"] = _public_review_url(ACP_COHORT_CONSOLE_PATH)
    result["next"] = ("cohort approved and frozen; ACP generation is a "
                      "separate explicit request")
    result["chat_summary"] = (
        f"Cohort version approved and frozen (immutable snapshot, "
        f"hash {result.get('snapshot_hash')}). No ACP was generated "
        f"and nothing was activated.")
    return result


async def _tool_generate_acp(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """generate_acp: GENERATE_ACP — run the deterministic induction
    against an APPROVED cohort version (frozen, snapshot-hash verified
    upstream); produces a review-ready draft; never activates."""
    cohort_version_id = _acp_arg_id(args, "acp_cohort_version_id",
                                     "acp_cohort_version_id")
    payload: Dict[str, Any] = {
        "acp_cohort_version_id": cohort_version_id,
        "actor_id": _acp_actor(ctx)}
    if args.get("idempotency_key"):
        payload["idempotency_key"] = str(args["idempotency_key"])[:128]
    result = await _acp_call("POST", f"{_ACP_BASE}/generation-runs",
                             payload)
    if "error" in result:
        error = result["error"]
        if error.get("upstream_code") == \
                "ACP_GENERATION_PREREQUISITES_INCOMPLETE":
            # Spec 021 / ADR-024: deterministic merge of the live
            # prerequisites detail so the model can report WHICH
            # companies are un-enriched and WHAT is missing — then stop
            # for the user's approval.  Bounded projection; no evidence
            # bodies, no tenant identifiers.  Review fix 14: the gate
            # blocks on FROZEN statuses of any member, so the projection
            # reports the frozen blockers and the `next` guidance
            # respects the version lifecycle (enrichment unblocks a
            # DRAFT version; an APPROVED version's manifest is
            # immutable and needs a NEW cohort version).
            detail = await _acp_call(
                "GET",
                f"{_ACP_BASE}/cohort-versions/{cohort_version_id}/"
                f"generation-prerequisites")
            if "error" not in detail:
                blocked = [
                    m for m in detail.get("members") or []
                    if m.get("decision") == "INSUFFICIENT_DATA"
                    or m.get("evidence_status_frozen") == "INSUFFICIENT"]
                error["unenriched_members"] = [
                    {"organization_id": m.get("organization_id"),
                     "canonical_legal_name": m.get("canonical_legal_name"),
                     "evidence_status": m.get("evidence_status_frozen"),
                     "evidence_status_live": m.get("evidence_status_live"),
                     "missing_fields": m.get("missing_fields")}
                    for m in blocked]
                error["policy_fields"] = (detail.get("policy") or {}).get(
                    "min_accepted_evidence_fields")
                error["frozen_evidence_insufficient"] = bool(
                    detail.get("frozen_evidence_insufficient"))
                if detail.get("frozen_evidence_insufficient"):
                    error["next"] = (
                        "the APPROVED version froze insufficient "
                        "evidence in its immutable manifest: report the "
                        "blocked companies, then tell the user that "
                        "enriching now requires a NEW cohort version "
                        "(re-propose after evidence is accepted); never "
                        "re-generate from the stale frozen manifest")
                else:
                    error["next"] = (
                        "report the un-enriched companies and their "
                        "missing fields, then STOP and ask the user to "
                        "approve enrichment (enrich_acp_cohort_evidence)"
                        "; never fabricate evidence and never proceed "
                        "without approval")
        return result
    if str(result.get("status") or "").upper() == "FAILED":
        return _acp_error(
            "generation_failure",
            f"the generation run failed "
            f"({result.get('failure_code') or 'unknown reason'}); no "
            f"ACP version was produced",
            generation_run_id=result.get("acp_generation_run_id"))
    summary = result.get("payload_summary") or {}
    out = {
        "generation_run_id": result.get("acp_generation_run_id"),
        "acp_version_id": result.get("acp_version_id"),
        "acp_id": result.get("acp_id"),
        "acp_version_number": result.get("acp_version_number"),
        "cohort_version_id": result.get("acp_cohort_version_id"),
        "status": result.get("status"),
        "snapshot_hash": result.get("snapshot_hash"),
        "payload_hash": result.get("payload_sha256"),
        "contributing_count": result.get("contributing_count"),
        "skipped_count": result.get("skipped_count"),
        "semantic_validation_status":
            result.get("semantic_validation_status"),
        "review_readiness": result.get("review_readiness"),
        "confidence_and_coverage": {
            "confidence": summary.get("confidence"),
            "dimension_count": summary.get("dimension_count"),
            "typed_dimension_count": summary.get("typed_dimension_count"),
        },
        "warnings": summary.get("warnings") or [],
        "idempotent_replay": bool(result.get("idempotent_replay")),
        "review_url": _public_review_url(ACP_CONSOLE_PATH),
    }
    out["next"] = ("the ACP draft is review-ready; review and "
                   "approval are separate explicit steps and the "
                   "active ACP is unchanged")
    if out["idempotent_replay"]:
        out["chat_summary"] = (
            "Idempotent replay: this cohort version already produced "
            "the recorded run; nothing was re-induced.")
    else:
        out["chat_summary"] = (
            f"ACP draft generated from the frozen snapshot "
            f"({out['contributing_count']} contributing, "
            f"{out['skipped_count']} skipped). Review it at "
            f"{out['review_url']} — the active ACP is unchanged.")
    return out


async def _tool_get_acp_generation_prerequisites(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """get_acp_generation_prerequisites: read the live evidence
    prerequisites of one cohort version (which members are un-enriched
    and which policy fields are missing). Read-only."""
    cohort_version_id = _acp_arg_id(args, "acp_cohort_version_id",
                                     "acp_cohort_version_id")
    result = await _acp_call(
        "GET",
        f"{_ACP_BASE}/cohort-versions/{cohort_version_id}/"
        f"generation-prerequisites")
    if "error" in result:
        return result
    out = {
        "cohort_version_id": result.get("cohort_version_id"),
        "version_status": result.get("version_status"),
        "ready": result.get("ready"),
        "frozen_evidence_insufficient":
            result.get("frozen_evidence_insufficient"),
        "policy_fields": (result.get("policy") or {}).get(
            "min_accepted_evidence_fields"),
        "members": [
            {"organization_id": m.get("organization_id"),
             "canonical_legal_name": m.get("canonical_legal_name"),
             "decision": m.get("decision"),
             # Live vs frozen are named explicitly (review fix 19): the
             # same key as _member_min_view would carry OPPOSITE
             # freshness semantics there (frozen).
             "evidence_status_live": m.get("evidence_status_live"),
             "evidence_status_frozen": m.get("evidence_status_frozen"),
             "missing_fields": m.get("missing_fields"),
             "stale_fields": m.get("stale_fields")}
            for m in result.get("members") or []],
        "review_url": _public_review_url(ACP_COHORT_CONSOLE_PATH),
    }
    out["next"] = (
        "if not ready: report the un-enriched companies and their "
        "missing fields, then STOP and ask the user to approve "
        "enrichment (enrich_acp_cohort_evidence); never fabricate "
        "evidence")
    state = "ready" if out["ready"] else "not ready"
    insufficient = sum(1 for m in out["members"]
                       if m["evidence_status_live"] == "INSUFFICIENT")
    out["chat_summary"] = (
        f"Evidence prerequisites: {state}; {insufficient} member(s) "
        f"lack required evidence.")
    return out


async def _tool_enrich_acp_cohort_evidence(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """enrich_acp_cohort_evidence: run the permission-gated evidence
    enrichment job over a cohort version's members, reusing the
    qualification research machinery. Researched values land as
    UNVERIFIED observations — acceptance is a separate explicit step;
    this never accepts and never generates."""
    cohort_version_id = _acp_arg_id(args, "acp_cohort_version_id",
                                     "acp_cohort_version_id")
    payload: Dict[str, Any] = {
        "actor_id": _acp_actor(ctx),
        "cohort_version_id": cohort_version_id}
    if args.get("organization_ids"):
        payload["organization_ids"] = [
            str(o) for o in args["organization_ids"]][:100]
    result = await _acp_call(
        "POST", f"{_ACP_BASE}/evidence-enrichment-jobs", payload)
    if "error" in result:
        return result
    out = {
        "job_id": result.get("job_id"),
        "state": result.get("state"),
        "cohort_version_id": result.get("cohort_version_id"),
        "organization_ids": result.get("organization_ids"),
        "field_targets": result.get("field_targets"),
    }
    out["next"] = ("poll get_acp_evidence_enrichment_job (once per "
                   "turn); when COMPLETED, present the per-company "
                   "field summary (values, source domains, unresolved "
                   "fields) and ask for SEPARATE explicit approval to "
                   "accept the recorded evidence")
    out["chat_summary"] = (
        f"Evidence enrichment job {out['job_id']} started for "
        f"{len(out['organization_ids'] or [])} company(ies); targets: "
        f"{', '.join(out['field_targets'] or [])}. Nothing is accepted "
        f"yet.")
    return out


async def _tool_get_acp_evidence_enrichment_job(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """get_acp_evidence_enrichment_job: read one enrichment job
    (status + bounded per-company results). Read-only."""
    job_id = _acp_arg_id(args, "job_id", "job_id")
    result = await _acp_call(
        "GET", f"{_ACP_BASE}/evidence-enrichment-jobs/{job_id}")
    # A dict-valued "error" is the tool-failure envelope; a job view
    # with a STRING error is a healthy response about a possibly FAILED
    # job — it must flow through the bounded projection so the FAILED
    # guidance below executes (review fix 15).
    if isinstance(result.get("error"), dict):
        return result
    out = {
        "job_id": result.get("job_id"),
        "state": result.get("state"),
        "field_targets": result.get("field_targets"),
        "warnings": result.get("warnings") or [],
        "error": result.get("error"),
        "companies": [],
        "observation_ids": result.get("observation_ids") or [],
    }
    for organization_id, company_result in (
            result.get("results") or {}).items():
        out["companies"].append({
            "organization_id": organization_id,
            "error": company_result.get("error"),
            "resolved": {
                field: {"value": detail.get("value"),
                        "source_system": detail.get("source_system"),
                        "source_url": detail.get("source_url"),
                        "confidence": detail.get("confidence"),
                        "observation_id": detail.get("observation_id")}
                for field, detail in (
                    company_result.get("resolved") or {}).items()},
            "unresolved_fields": company_result.get("unresolved_fields"),
            "skipped_fields": company_result.get("skipped_fields"),
        })
    if out["state"] == "COMPLETED":
        out["next"] = ("present the per-company summary and ask for "
                       "SEPARATE explicit approval to accept the "
                       "recorded evidence "
                       "(accept_acp_enrichment_evidence)")
    elif out["state"] == "FAILED":
        out["next"] = "report the failure; do not retry without the user"
    else:
        out["next"] = ("the job is still running; poll again on the "
                       "user's next message (once per turn)")
    out["chat_summary"] = (
        f"Enrichment job {job_id}: {out['state']}; "
        f"{len(out['companies'])} company(ies).")
    return out


async def _tool_accept_acp_enrichment_evidence(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """accept_acp_enrichment_evidence: audited acceptance of the
    enrichment job's recorded UNVERIFIED observations (separate
    explicit user approval; supersedes the previous accepted row per
    field). Never generates."""
    job_id = _acp_arg_id(args, "job_id", "job_id")
    payload: Dict[str, Any] = {"actor_id": _acp_actor(ctx)}
    if args.get("observation_ids"):
        payload["observation_ids"] = [
            str(o) for o in args["observation_ids"]][:500]
    result = await _acp_call(
        "POST", f"{_ACP_BASE}/evidence-enrichment-jobs/{job_id}/accept",
        payload)
    if "error" in result:
        return result
    out = {
        "job_id": result.get("job_id"),
        "accepted_count": result.get("accepted_count"),
        "accepted": [
            {"observation_id": a.get("observation_id"),
             "field_key": a.get("field_key")}
            for a in result.get("accepted") or []],
    }
    out["next"] = ("evidence accepted; continue the staged workflow — "
                   "a DRAFT cohort version can proceed to member "
                   "decisions and approval (which re-freezes evidence), "
                   "while an APPROVED version with frozen insufficient "
                   "evidence requires a NEW cohort version "
                   "(re-proposal) before generation")
    out["chat_summary"] = (
        f"Accepted {out['accepted_count']} evidence observation(s) "
        f"from job {job_id} (audited; supersession per field).")
    return out


async def _tool_get_acp_generation_run(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """get_acp_generation_run: read one generation run."""
    run_id = _acp_arg_id(args, "generation_run_id", "generation_run_id")
    result = await _acp_call(
        "GET", f"{_ACP_BASE}/generation-runs/{run_id}")
    if "error" in result:
        return result
    summary = result.get("payload_summary") or {}
    out = {
        "generation_run_id": result.get("acp_generation_run_id"),
        "cohort_version_id": result.get("acp_cohort_version_id"),
        "status": result.get("status"),
        "snapshot_hash": result.get("snapshot_hash"),
        "acp_version_id": result.get("acp_version_id"),
        "payload_hash": result.get("payload_sha256"),
        "contributing_count": result.get("contributing_count"),
        "skipped_count": result.get("skipped_count"),
        "failure_code": result.get("failure_code"),
        "confidence_and_coverage": {
            "confidence": summary.get("confidence"),
            "dimension_count": summary.get("dimension_count"),
            "typed_dimension_count": summary.get("typed_dimension_count"),
        },
        "warnings": summary.get("warnings") or [],
        "review_url": _public_review_url(ACP_CONSOLE_PATH),
    }
    out["chat_summary"] = (
        f"Generation run {run_id}: status {out['status']}, snapshot "
        f"{out['snapshot_hash']}.")
    return out


async def _tool_get_acp_version(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """get_acp_version: read one ACP version (typed projection)."""
    acp_id = _acp_arg_id(args, "acp_id", "acp_id")
    version_number = int(args.get("version_number") or 0)
    if version_number <= 0:
        raise ToolExecutionError("invalid_arguments",
                                 "version_number is required.")
    result = await _acp_call(
        "GET", f"{_ACP_BASE}/versions/{acp_id}/{version_number}")
    if "error" in result:
        return result
    result["review_url"] = _public_review_url(ACP_CONSOLE_PATH)
    result["chat_summary"] = (
        f"ACP {acp_id} v{version_number}: {result.get('status')} "
        f"(validation {result.get('semantic_validation_status')}, "
        f"readiness {result.get('review_readiness')}).")
    return result


async def _tool_submit_acp_for_review(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """submit_acp_for_review: REVIEW_ACP — DRAFT -> REVIEW_READY
    (payload byte-identical upstream; no generation, no scoring)."""
    acp_id = _acp_arg_id(args, "acp_id", "acp_id")
    version_number = int(args.get("version_number") or 0)
    if version_number <= 0:
        raise ToolExecutionError("invalid_arguments",
                                 "version_number is required.")
    result = await _acp_call(
        "POST",
        f"{_ACP_BASE}/versions/{acp_id}/{version_number}/submit-review",
        {"actor_id": _acp_actor(ctx)})
    if "error" in result:
        return result
    result["review_url"] = _public_review_url(ACP_CONSOLE_PATH)
    result["chat_summary"] = (
        "ACP draft submitted for review; the payload is "
        "byte-identical and unchanged.")
    return result


async def _tool_approve_acp(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """approve_acp: APPROVE_ACP — append the immutable approval record;
    never activates (the active ACP stays unchanged).  A REVIEW_READY
    version is moved to UNDER_REVIEW first (accepted API transition;
    the approval intent itself remains the explicit user request)."""
    acp_id = _acp_arg_id(args, "acp_id", "acp_id")
    version_number = int(args.get("version_number") or 0)
    if version_number <= 0:
        raise ToolExecutionError("invalid_arguments",
                                 "version_number is required.")
    current = await _acp_call(
        "GET", f"{_ACP_BASE}/versions/{acp_id}/{version_number}")
    if "error" in current:
        return current
    if current.get("status") == "REVIEW_READY":
        started = await _acp_call(
            "POST",
            f"{_ACP_BASE}/versions/{acp_id}/{version_number}/"
            f"start-review", {"actor_id": _acp_actor(ctx)})
        if "error" in started:
            return started
    payload: Dict[str, Any] = {
        "decision": "APPROVED", "actor_id": _acp_actor(ctx)}
    if args.get("comments"):
        payload["comments"] = str(args["comments"])[:500]
    result = await _acp_call(
        "POST",
        f"{_ACP_BASE}/versions/{acp_id}/{version_number}/approve",
        payload)
    if "error" in result:
        return result
    result["activation_ready"] = True
    result["active_acp_unchanged"] = True
    result["chat_summary"] = (
        f"ACP {acp_id} v{version_number} approved (immutable approval "
        f"record). Activation is a separate explicit step; the "
        f"currently active ACP is unchanged.")
    return result


async def _tool_activate_acp(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """activate_acp: ACTIVATE_ACP — transactionally activate an
    APPROVED ACP version (exactly one active per tenant; ledger + audit
    upstream; rollback preserved)."""
    acp_id = _acp_arg_id(args, "acp_id", "acp_id")
    version_number = int(args.get("version_number") or 0)
    if version_number <= 0:
        raise ToolExecutionError("invalid_arguments",
                                 "version_number is required.")
    payload: Dict[str, Any] = {"actor_id": _acp_actor(ctx)}
    if args.get("reason"):
        payload["reason"] = str(args["reason"])[:500]
    result = await _acp_call(
        "POST",
        f"{_ACP_BASE}/versions/{acp_id}/{version_number}/activate",
        payload)
    if "error" in result:
        if result["error"].get("code") == "activation_conflict":
            result["error"]["message"] = (
                "another ACP version is already ACTIVE for this "
                "tenant; the accepted activation operation fails "
                "closed instead of superseding — request an explicit "
                "rollback of the active ACP or perform the supersession "
                "through the operator workflow")
        return result
    # Single-active verification + ledger reference from the accepted
    # read surfaces (no local activation logic).
    active = await _acp_call("GET", f"{_ACP_BASE}/active")
    lineage = await _acp_call(
        "GET",
        f"{_ACP_BASE}/versions/{acp_id}/{version_number}/lineage")
    activations = (lineage.get("activations") or []) \
        if "error" not in lineage else []
    newest = activations[-1] if activations else {}
    single_active = (
        "error" not in active
        and active.get("acp_id") == acp_id
        and active.get("version") == version_number)
    out = {
        "activation_id": newest.get("activation_id"),
        "active_acp_id": active.get("acp_id")
        if "error" not in active else acp_id,
        "active_acp_version": active.get("version")
        if "error" not in active else version_number,
        "status": result.get("status"),
        "superseded_acp_id": None,
        "superseded_acp_version": None,
        "activated_at": newest.get("activated_at"),
        "rollback_reference": newest.get("activation_id"),
        "single_active": single_active,
        "previous_active_acp_unchanged": False,
        "review_url": _public_review_url(ACP_CONSOLE_PATH),
    }
    out["chat_summary"] = (
        f"ACP {acp_id} v{version_number} is now ACTIVE "
        f"(activation {out['activation_id']}; single-active verified: "
        f"{single_active}). Rollback remains available as an explicit "
        f"operation.")
    return out


async def _tool_rollback_acp_activation(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """rollback_acp_activation: ACTIVATE_ACP — restore a previously
    active ACP version through the activation ledger (a new ledger
    operation; history is never rewritten)."""
    acp_id = _acp_arg_id(args, "acp_id", "acp_id")
    version_number = int(args.get("version_number") or 0)
    if version_number <= 0:
        raise ToolExecutionError("invalid_arguments",
                                 "version_number is required.")
    payload: Dict[str, Any] = {"actor_id": _acp_actor(ctx)}
    if args.get("rollback_of_activation_id"):
        payload["rollback_of_activation_id"] = \
            str(args["rollback_of_activation_id"])[:64]
    if args.get("reason"):
        payload["reason"] = str(args["reason"])[:500]
    result = await _acp_call(
        "POST",
        f"{_ACP_BASE}/versions/{acp_id}/{version_number}/rollback",
        payload)
    if "error" in result:
        return result
    lineage = await _acp_call(
        "GET",
        f"{_ACP_BASE}/versions/{acp_id}/{version_number}/lineage")
    activations = (lineage.get("activations") or []) \
        if "error" not in lineage else []
    newest = activations[-1] if activations else {}
    active = await _acp_call("GET", f"{_ACP_BASE}/active")
    single_active = (
        "error" not in active
        and active.get("acp_id") == acp_id
        and active.get("version") == version_number)
    out = {
        "restored_acp_id": result.get("acp_id"),
        "restored_acp_version": result.get("version"),
        "status": result.get("status"),
        "activation_id": newest.get("activation_id"),
        "rollback_of_activation_id":
            newest.get("rollback_of_activation_id"),
        "rolled_back_at": newest.get("activated_at"),
        "single_active": single_active,
        "history_preserved": True,
        "review_url": _public_review_url(ACP_CONSOLE_PATH),
    }
    out["chat_summary"] = (
        f"Rollback recorded as a new ledger operation: ACP {acp_id} "
        f"v{version_number} is ACTIVE again "
        f"(activation {out['activation_id']}); prior history is "
        f"preserved.")
    return out


async def _tool_get_active_acp(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """get_active_acp: resolve the tenant's ACTIVE ACP (bounded
    projection; no profile payload content)."""
    result = await _acp_call("GET", f"{_ACP_BASE}/active")
    if "error" in result:
        return result
    profile = result.get("profile") or {}
    out = {
        "acp_id": result.get("acp_id"),
        "icp_id": result.get("icp_id"),
        "version": result.get("version"),
        "icp_version": result.get("icp_version"),
        "status": result.get("status"),
        "origin": result.get("origin"),
        "cohort_version_id": result.get("cohort_version_id"),
        "payload_sha256": result.get("payload_sha256"),
        "approved_at": result.get("approved_at"),
        "label": profile.get("label"),
    }
    out["review_url"] = _public_review_url(ACP_CONSOLE_PATH)
    out["chat_summary"] = (
        f"Active ACP: {result.get('acp_id')} "
        f"v{result.get('version')} ({result.get('origin')}).")
    return out


async def _tool_get_acp_lineage(
        args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """get_acp_lineage: VIEW_ACP_AUDIT — cohort, snapshot hash,
    generation run, approvals, activations (opaque ids and hashes
    only)."""
    acp_id = _acp_arg_id(args, "acp_id", "acp_id")
    version_number = int(args.get("version_number") or 0)
    if version_number <= 0:
        raise ToolExecutionError("invalid_arguments",
                                 "version_number is required.")
    result = await _acp_call(
        "GET",
        f"{_ACP_BASE}/versions/{acp_id}/{version_number}/lineage")
    if "error" in result:
        return result
    result["chat_summary"] = (
        f"Lineage for ACP {acp_id} v{version_number}: cohort "
        f"{result.get('cohort_id')}, snapshot "
        f"{result.get('cohort_version_snapshot_hash')}, run "
        f"{result.get('generation_run_id')}, "
        f"{len(result.get('approvals') or [])} approvals, "
        f"{len(result.get('activations') or [])} activation records.")
    return result




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

