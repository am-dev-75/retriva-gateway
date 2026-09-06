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
Gateway proxy routes for session attachments, artifacts, and CRM Assistant.

These routes forward requests to Retriva Core's ingestion API (port 8000),
which hosts the session document processing endpoints and the CRM
Assistant extension router.

The Gateway is a thin pass-through: it adds no business logic and
preserves Core's status codes.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form, status
from fastapi.responses import StreamingResponse, Response
from loguru import logger

from retriva_gateway.core.client import core_client

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

@router.post("/{session_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(session_id: str, file: UploadFile = File(...), owner: Optional[str] = Form(None)):
    """Upload a session-scoped attachment to Core."""
    content = await file.read()
    # Forward as multipart to Core.
    import httpx
    url = f"{core_client.ingestion_base_url.rstrip('/')}/api/v2/sessions/{session_id}/attachments"
    headers = core_client._get_headers()
    files = {"file": (file.filename, content, file.content_type or "application/octet-stream")}
    data = {}
    if owner:
        data["owner"] = owner
    async with httpx.AsyncClient(timeout=core_client.timeout) as client:
        resp = await client.post(url, headers=headers, files=files, data=data)
    if resp.status_code == 401:
        await core_client._handle401(resp)
    if resp.status_code != 201:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@router.get("/{session_id}/attachments")
async def list_attachments(session_id: str):
    return await core_client._request("GET", core_client.ingestion_base_url, f"/api/v2/sessions/{session_id}/attachments")


@router.get("/{session_id}/attachments/{attachment_id}")
async def get_attachment(session_id: str, attachment_id: str):
    try:
        return await core_client._request(
            "GET", core_client.ingestion_base_url,
            f"/api/v2/sessions/{session_id}/attachments/{attachment_id}",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.post("/{session_id}/attachments/{attachment_id}/parse")
async def parse_attachment(session_id: str, attachment_id: str):
    try:
        return await core_client._request(
            "POST", core_client.ingestion_base_url,
            f"/api/v2/sessions/{session_id}/attachments/{attachment_id}/parse",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.delete("/{session_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(session_id: str, attachment_id: str):
    try:
        await core_client._request(
            "DELETE", core_client.ingestion_base_url,
            f"/api/v2/sessions/{session_id}/attachments/{attachment_id}",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

@router.get("/{session_id}/artifacts")
async def list_artifacts(session_id: str):
    return await core_client._request("GET", core_client.ingestion_base_url, f"/api/v2/sessions/{session_id}/artifacts")


@router.get("/{session_id}/artifacts/{artifact_id}")
async def get_artifact(session_id: str, artifact_id: str):
    try:
        return await core_client._request(
            "GET", core_client.ingestion_base_url,
            f"/api/v2/sessions/{session_id}/artifacts/{artifact_id}",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.get("/{session_id}/artifacts/{artifact_id}/content")
async def download_artifact(session_id: str, artifact_id: str):
    """Download artifact content, streaming from Core."""
    import httpx
    url = f"{core_client.ingestion_base_url.rstrip('/')}/api/v2/sessions/{session_id}/artifacts/{artifact_id}/content"
    headers = core_client._get_headers()
    async with httpx.AsyncClient(timeout=core_client.timeout) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "application/octet-stream"),
        headers={"Content-Disposition": resp.headers.get("content-disposition", f'attachment; filename="{artifact_id}"')},
    )


@router.delete("/{session_id}/artifacts/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_artifact(session_id: str, artifact_id: str):
    try:
        await core_client._request(
            "DELETE", core_client.ingestion_base_url,
            f"/api/v2/sessions/{session_id}/artifacts/{artifact_id}",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Late import for exception handling
import httpx  # noqa: E402