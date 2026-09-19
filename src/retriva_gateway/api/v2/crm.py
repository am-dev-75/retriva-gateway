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
Gateway proxy routes for the CRM Assistant extension.

Forwards requests to Retriva Core's ingestion API (port 8000), which hosts
the CRM Assistant extension router at /api/v2/crm/*.

The Gateway is a thin pass-through.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from loguru import logger
import httpx

from retriva_gateway.core.client import core_client

router = APIRouter(prefix="/crm", tags=["crm-assistant"])


class QualifyRequest(BaseModel):
    session_id: str
    attachment_id: str
    kb_id: str = "default"
    collection_name: Optional[str] = None
    # Request-level approved-store reuse policy, passed through to the
    # CRM extension (PREFER_APPROVED | FORCE_REQUALIFICATION |
    # COMPARE_WITH_APPROVED | ...).
    reuse_policy: Optional[str] = None


@router.get("/health")
async def crm_health():
    try:
        resp = await core_client._request("GET", core_client.ingestion_base_url, "/api/v2/crm/health")
        return resp.json()
    except Exception as e:
        return {"status": "unavailable", "error": str(e)}


@router.get("/readiness")
async def crm_readiness():
    """Structured qualification preflight/readiness (proxied from Core).

    Reports web-research provider readiness (mock-only detection), ACP/CCO
    readiness semantics, and whether qualification can proceed.  Consumed by
    the chat agent preflight tool.
    """
    try:
        resp = await core_client._request("GET", core_client.ingestion_base_url, "/api/v2/crm/readiness")
        return resp.json()
    except Exception as e:
        return {"status": "unavailable", "error": str(e)}


@router.post("/qualify", status_code=status.HTTP_202_ACCEPTED)
async def crm_qualify(request: QualifyRequest):
    """Start a CRM qualification job."""
    try:
        resp = await core_client._request(
            "POST", core_client.ingestion_base_url, "/api/v2/crm/qualify",
            json=request.model_dump(),
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.get("/jobs/{job_id}")
async def crm_get_job(job_id: str):
    try:
        resp = await core_client._request(
            "GET", core_client.ingestion_base_url, f"/api/v2/crm/jobs/{job_id}",
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.get("/jobs/{job_id}/results")
async def crm_get_job_results(job_id: str):
    """Proxy the structured per-candidate results of a completed job.

    Pure transport: mirrors the CRM extension's /jobs/{job_id}/results
    (409 until COMPLETED*, 410 after eviction). The E2E harness uses this
    for acceptance checks and ACP/CCO binding verification.
    """
    try:
        resp = await core_client._request(
            "GET", core_client.ingestion_base_url,
            f"/api/v2/crm/jobs/{job_id}/results",
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.get("/sessions/{session_id}/jobs")
async def crm_list_session_jobs(session_id: str):
    """Proxy the session-scoped job listing.

    Enables clients (E2E harness, cross-turn chat resumption) to discover
    the jobs of THEIR OWN session without relying on LLM-remembered job IDs.
    """
    try:
        resp = await core_client._request(
            "GET", core_client.ingestion_base_url,
            f"/api/v2/crm/sessions/{session_id}/jobs",
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.post("/jobs/{job_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def crm_cancel_job(job_id: str):
    try:
        resp = await core_client._request(
            "POST", core_client.ingestion_base_url, f"/api/v2/crm/jobs/{job_id}/cancel",
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.get("/portfolio/{kb_id}")
async def crm_get_portfolio(kb_id: str, collection_name: Optional[str] = None):
    params = {"collection_name": collection_name} if collection_name else None
    try:
        resp = await core_client._request(
            "GET", core_client.ingestion_base_url, f"/api/v2/crm/portfolio/{kb_id}",
            params=params,
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.post("/portfolio/{kb_id}/rebuild")
async def crm_rebuild_portfolio(kb_id: str, collection_name: Optional[str] = None):
    params = {"collection_name": collection_name} if collection_name else None
    try:
        resp = await core_client._request(
            "POST", core_client.ingestion_base_url, f"/api/v2/crm/portfolio/{kb_id}/rebuild",
            params=params,
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.get("/acp/{kb_id}")
@router.get("/icp/{kb_id}", deprecated=True)  # deprecated alias of /acp/
async def crm_get_icp(kb_id: str, collection_name: Optional[str] = None):
    params = {"collection_name": collection_name} if collection_name else None
    try:
        resp = await core_client._request(
            "GET", core_client.ingestion_base_url, f"/api/v2/crm/icp/{kb_id}",
            params=params,
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


# --- ICP / CCO global variable text (user-editable) ---

@router.get("/acp/{kb_id}/text")
@router.get("/icp/{kb_id}/text", deprecated=True)  # deprecated alias
async def crm_get_icp_text(kb_id: str):
    try:
        resp = await core_client._request(
            "GET", core_client.ingestion_base_url, f"/api/v2/crm/icp/{kb_id}/text",
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.put("/acp/{kb_id}/text")
@router.put("/icp/{kb_id}/text", deprecated=True)  # deprecated alias
async def crm_save_icp_text(kb_id: str, body: dict):
    try:
        resp = await core_client._request(
            "PUT", core_client.ingestion_base_url, f"/api/v2/crm/icp/{kb_id}/text",
            json=body,
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.post("/acp/{kb_id}/update")
@router.post("/icp/{kb_id}/update", deprecated=True)  # deprecated alias
async def crm_update_icp(kb_id: str, collection_name: Optional[str] = None):
    params = {"collection_name": collection_name} if collection_name else None
    try:
        resp = await core_client._request(
            "POST", core_client.ingestion_base_url, f"/api/v2/crm/icp/{kb_id}/update",
            params=params,
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.get("/cco/{kb_id}/text")
async def crm_get_cco_text(kb_id: str):
    try:
        resp = await core_client._request(
            "GET", core_client.ingestion_base_url, f"/api/v2/crm/cco/{kb_id}/text",
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.put("/cco/{kb_id}/text")
async def crm_save_cco_text(kb_id: str, body: dict):
    try:
        resp = await core_client._request(
            "PUT", core_client.ingestion_base_url, f"/api/v2/crm/cco/{kb_id}/text",
            json=body,
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.post("/cco/{kb_id}/update")
async def crm_update_cco(kb_id: str, collection_name: Optional[str] = None):
    params = {"collection_name": collection_name} if collection_name else None
    try:
        resp = await core_client._request(
            "POST", core_client.ingestion_base_url, f"/api/v2/crm/cco/{kb_id}/update",
            params=params,
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)

# ---------------------------------------------------------------------------
# Human-approved Company Intelligence Store (review API pass-through).
# Pure transport: mirrors the CRM extension's /intelligence/* endpoints
# (qualification review queue, approval/rejection/revocation, history,
# comparison, metrics, schema status and the review UI page).
# ---------------------------------------------------------------------------

_INTEL_PATHS = {
    ("GET", "/intelligence/assessments"),
    ("POST", "/intelligence/assessments"),
    ("GET", "/intelligence/assessments/{assessment_id}"),
    ("POST", "/intelligence/assessments/{assessment_id}/submit-review"),
    ("POST", "/intelligence/assessments/{assessment_id}/approve"),
    ("GET", "/intelligence/companies/{identity_id}/history"),
    ("GET", "/intelligence/companies/{identity_id}/latest-approved"),
    ("GET", "/intelligence/assessments/{a_id}/compare/{b_id}"),
    ("GET", "/intelligence/metrics"),
    ("GET", "/intelligence/schema"),
    ("GET", "/intelligence/review"),
}


async def _proxy_intelligence(method: str, sub_path: str, body=None):
    try:
        kwargs = {}
        if body is not None:
            kwargs["json"] = body
        resp = await core_client._request(
            method, core_client.ingestion_base_url,
            f"/api/v2/crm/intelligence{sub_path}", **kwargs)
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type"),
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=e.response.text)


@router.get("/intelligence/assessments")
async def intel_list_assessments(status_filter: Optional[str] = None,
                                  awaiting_review: bool = False):
    return await _proxy_intelligence(
        "GET",
        f"/assessments?status_filter={status_filter or ''}"
        f"&awaiting_review={'true' if awaiting_review else 'false'}")


@router.post("/intelligence/assessments")
async def intel_create_assessment(body: dict):
    return await _proxy_intelligence("POST", "/assessments", body)


@router.get("/intelligence/assessments/{assessment_id}")
async def intel_get_assessment(assessment_id: str):
    return await _proxy_intelligence(
        "GET", f"/assessments/{assessment_id}")


@router.post(
    "/intelligence/assessments/{assessment_id}/submit-review")
async def intel_submit_review(assessment_id: str):
    return await _proxy_intelligence(
        "POST", f"/assessments/{assessment_id}/submit-review", {})


@router.post("/intelligence/assessments/{assessment_id}/approve")
async def intel_approve(assessment_id: str, body: dict):
    return await _proxy_intelligence(
        "POST", f"/assessments/{assessment_id}/approve", body)


@router.get("/intelligence/companies/{identity_id}/history")
async def intel_company_history(identity_id: str):
    return await _proxy_intelligence(
        "GET", f"/companies/{identity_id}/history")


@router.get(
    "/intelligence/companies/{identity_id}/latest-approved")
async def intel_latest_approved(identity_id: str):
    return await _proxy_intelligence(
        "GET", f"/companies/{identity_id}/latest-approved")


@router.get("/intelligence/assessments/{a_id}/compare/{b_id}")
async def intel_compare(a_id: str, b_id: str):
    return await _proxy_intelligence("GET", f"/assessments/{a_id}/compare/{b_id}")


@router.get("/intelligence/metrics")
async def intel_metrics():
    return await _proxy_intelligence("GET", "/metrics")


@router.get("/intelligence/schema")
async def intel_schema():
    return await _proxy_intelligence("GET", "/schema")


@router.get("/intelligence/review")
async def intel_review_page():
    return await _proxy_intelligence("GET", "/review")


# ---------------------------------------------------------------------------
# Durable Completed-Job Archive (Milestone A) — pass-through mirrors of the
# CRM extension's /archive/* endpoints: archived jobs, candidate results,
# assessment drafts (incl. approve/reject/request-research), artifacts,
# retry lineage, retry-from-archive and schema status.
# ---------------------------------------------------------------------------

async def _proxy_archive(method: str, sub_path: str, body=None,
                         params: Optional[dict] = None):
    """Forward to Core's /api/v2/crm/archive/* (pure transport)."""
    try:
        kwargs = {}
        if body is not None:
            kwargs["json"] = body
        if params:
            kwargs["params"] = {k: v for k, v in params.items()
                                if v is not None}
        resp = await core_client._request(
            method, core_client.ingestion_base_url,
            f"/api/v2/crm/archive{sub_path}", **kwargs)
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type"),
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code, detail=e.response.text)


@router.get("/archive/jobs")
async def archive_list_jobs(session_id: Optional[str] = None,
                            state: Optional[str] = None,
                            limit: int = 50,
                            offset: int = 0,
                            order: str = "desc"):
    return await _proxy_archive(
        "GET", "/jobs", params={
            "session_id": session_id, "state": state, "limit": limit,
            "offset": offset, "order": order})


@router.get("/archive/jobs/{job_id}")
async def archive_get_job(job_id: str):
    return await _proxy_archive("GET", f"/jobs/{job_id}")


@router.get("/archive/jobs/{job_id}/results")
async def archive_get_results(job_id: str):
    return await _proxy_archive("GET", f"/jobs/{job_id}/results")


@router.get("/archive/jobs/{job_id}/candidates/{candidate_id}")
async def archive_get_candidate(job_id: str, candidate_id: str):
    return await _proxy_archive(
        "GET", f"/jobs/{job_id}/candidates/{candidate_id}")


@router.get("/archive/jobs/{job_id}/lineage")
async def archive_get_lineage(job_id: str):
    return await _proxy_archive("GET", f"/jobs/{job_id}/lineage")


@router.get("/archive/jobs/{job_id}/drafts")
async def archive_list_drafts(job_id: str,
                              review_status: Optional[str] = None,
                              limit: int = 100,
                              offset: int = 0):
    return await _proxy_archive(
        "GET", f"/jobs/{job_id}/drafts", params={
            "review_status": review_status, "limit": limit,
            "offset": offset})


@router.get("/archive/jobs/{job_id}/artifacts")
async def archive_list_artifacts(job_id: str):
    return await _proxy_archive("GET", f"/jobs/{job_id}/artifacts")


@router.post("/archive/jobs/{job_id}/retry")
async def archive_retry_job(job_id: str, body: dict):
    return await _proxy_archive("POST", f"/jobs/{job_id}/retry", body)


@router.get("/archive/drafts")
async def archive_list_all_drafts(review_status: Optional[str] = None,
                                 limit: int = 100,
                                 offset: int = 0):
    return await _proxy_archive(
        "GET", "/drafts", params={
            "review_status": review_status, "limit": limit,
            "offset": offset})


@router.get("/archive/drafts/{draft_id}")
async def archive_get_draft(draft_id: str):
    return await _proxy_archive("GET", f"/drafts/{draft_id}")


@router.post("/archive/drafts/{draft_id}/approve")
async def archive_approve_draft(draft_id: str, body: dict):
    return await _proxy_archive("POST", f"/drafts/{draft_id}/approve", body)


@router.post("/archive/drafts/{draft_id}/reject")
async def archive_reject_draft(draft_id: str, body: dict):
    return await _proxy_archive("POST", f"/drafts/{draft_id}/reject", body)


@router.post("/archive/drafts/{draft_id}/request-research")
async def archive_request_research(draft_id: str, body: dict):
    return await _proxy_archive(
        "POST", f"/drafts/{draft_id}/request-research", body)


@router.get("/archive/research-requests")
async def archive_list_research_requests(status_filter: Optional[str] = None,
                                         limit: int = 100):
    return await _proxy_archive(
        "GET", "/research-requests", params={
            "status_filter": status_filter, "limit": limit})


@router.get("/archive/artifacts/{artifact_id}/content")
async def archive_read_artifact(artifact_id: str):
    return await _proxy_archive("GET", f"/artifacts/{artifact_id}/content")


@router.get("/archive/schema")
async def archive_schema():
    return await _proxy_archive("GET", "/schema")
