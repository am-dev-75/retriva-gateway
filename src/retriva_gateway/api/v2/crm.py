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

    Reports web-research provider readiness (mock-only detection), ICP/CCO
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


@router.get("/icp/{kb_id}")
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

@router.get("/icp/{kb_id}/text")
async def crm_get_icp_text(kb_id: str):
    try:
        resp = await core_client._request(
            "GET", core_client.ingestion_base_url, f"/api/v2/crm/icp/{kb_id}/text",
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.put("/icp/{kb_id}/text")
async def crm_save_icp_text(kb_id: str, body: dict):
    try:
        resp = await core_client._request(
            "PUT", core_client.ingestion_base_url, f"/api/v2/crm/icp/{kb_id}/text",
            json=body,
        )
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.post("/icp/{kb_id}/update")
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