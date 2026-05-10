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

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from retriva_gateway.core.client import core_client
from retriva_gateway.config import settings

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

class ArtifactRequest(BaseModel):
    artifact_type: str
    format: str
    parameters: Optional[Dict[str, Any]] = None

@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_artifact(request: ArtifactRequest):
    if not settings.GATEWAY_ENABLE_ARTIFACTS:
        raise HTTPException(status_code=501, detail="Artifacts are disabled")
    
    try:
        response = await core_client.create_artifact(request.model_dump())
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("")
async def list_artifacts():
    # Core doesn't have a list artifacts endpoint in the router I saw? 
    # Let me check v2_artifacts.py again.
    # Actually, it doesn't have a list all artifacts endpoint.
    return []

@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str):
    try:
        return await core_client.get_artifact(artifact_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail="Artifact not found")

@router.get("/{artifact_id}/content")
async def download_artifact(artifact_id: str):
    try:
        response = await core_client.download_artifact(artifact_id)
        # We need to stream the content back
        return StreamingResponse(
            response.aiter_bytes(),
            media_type=response.headers.get("content-type", "application/octet-stream"),
            headers={
                "Content-Disposition": response.headers.get("content-disposition", "")
            }
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail="Artifact not found or not ready")

@router.delete("/{artifact_id}")
async def delete_artifact(artifact_id: str):
    try:
        await core_client.delete_artifact(artifact_id)
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
