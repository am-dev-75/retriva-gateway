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

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status
from typing import List, Optional, Dict, Any
import uuid
from pydantic import BaseModel
from retriva_gateway.core.client import core_client
from loguru import logger
import json
import os
from pathlib import Path
from retriva_gateway.config import settings

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

# Simple in-memory store for batches (for first implementation)
# In production, this would be a database.
batches: Dict[str, Dict[str, Any]] = {}

class BatchCreateRequest(BaseModel):
    metadata: Optional[Dict[str, Any]] = None
    source_type: Optional[str] = "auto"

class BatchResponse(BaseModel):
    batch_id: str
    status: str
    files: List[Dict[str, Any]] = []
    metadata: Optional[Dict[str, Any]] = None

@router.post("/batches", response_model=BatchResponse)
async def create_batch(request: BatchCreateRequest):
    batch_id = str(uuid.uuid4())
    batches[batch_id] = {
        "batch_id": batch_id,
        "status": "active",
        "files": [],
        "metadata": request.metadata or {},
        "source_type": request.source_type or "auto"
    }
    return batches[batch_id]

@router.post("/batches/{batch_id}/files")
async def upload_file_to_batch(
    batch_id: str,
    file: UploadFile = File(...),
    source_path: str = Form(...),
    user_metadata: Optional[str] = Form(None)
):
    if batch_id not in batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    # Merge batch metadata and per-file metadata
    batch_metadata = batches[batch_id].get("metadata", {})
    file_metadata = {}
    if user_metadata:
        try:
            file_metadata = json.loads(user_metadata)
        except json.JSONDecodeError:
            raise HTTPException(status_code=422, detail="Invalid JSON in user_metadata")
    
    # Merged metadata (file metadata takes precedence if keys overlap)
    merged_metadata = {**batch_metadata, **file_metadata}
    
    batch_info = batches[batch_id]
    
    if batch_info.get("source_type") == "mediawiki_export":
        # Stage file locally
        file_bytes = await file.read()
        target_path = Path(settings.GATEWAY_UPLOAD_TMP_DIR) / batch_id / source_path.lstrip("/")
        
        # Prevent path traversal
        if not os.path.abspath(target_path).startswith(os.path.abspath(Path(settings.GATEWAY_UPLOAD_TMP_DIR) / batch_id)):
            raise HTTPException(status_code=400, detail="Invalid source path")
            
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "wb") as f:
            f.write(file_bytes)
            
        file_info = {
            "filename": file.filename,
            "source_path": source_path,
            "status": "staged"
        }
        batch_info["files"].append(file_info)
        return file_info
    
    # Forward to Core
    # Core expects multipart: file, source_path, user_metadata (JSON string)
    try:
        core_response = await core_client.upload_file_to_batch(
            batch_id=batch_id, # This is just a path param in Gateway, not necessarily in Core
            files={"file": (file.filename, file.file, file.content_type)},
            data={
                "source_path": source_path,
                "user_metadata": json.dumps(merged_metadata)
            }
        )
        
        # Track file in batch
        file_info = {
            "filename": file.filename,
            "source_path": source_path,
            "job_id": core_response.get("job_id"),
            "status": "accepted"
        }
        batches[batch_id]["files"].append(file_info)
        
        return file_info
    except Exception as e:
        logger.error(f"Failed to forward file to Core: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/batches/{batch_id}", response_model=BatchResponse)
async def get_batch(batch_id: str):
    if batch_id not in batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    batch = batches[batch_id]
    
    # Update file statuses from Core
    for file_info in batch["files"]:
        if file_info.get("job_id"):
            try:
                job_status = await core_client.get_batch_status(file_info["job_id"])
                file_info["status"] = job_status.get("status", "unknown")
            except Exception as e:
                logger.warning(f"Could not get status for job {file_info['job_id']}: {e}")
    
    return batch


class FinalizeBatchResponse(BaseModel):
    job_id: str
    status: str

@router.post("/batches/{batch_id}/finalize", response_model=FinalizeBatchResponse)
async def finalize_batch(batch_id: str):
    if batch_id not in batches:
        raise HTTPException(status_code=404, detail="Batch not found")
        
    batch_info = batches[batch_id]
    if batch_info.get("source_type") != "mediawiki_export":
        raise HTTPException(status_code=400, detail="Batch is not a staged mediawiki_export batch")
        
    staged_dir = Path(settings.GATEWAY_UPLOAD_TMP_DIR) / batch_id
    if not staged_dir.exists() or not staged_dir.is_dir():
        raise HTTPException(status_code=400, detail="No staged files found for batch")
        
    try:
        core_response = await core_client.ingest_mediawiki_export({
            "staged_dir": str(staged_dir.absolute()),
            "kb_id": "default",
            "user_metadata": batch_info.get("metadata", {})
        })
        
        batch_info["status"] = "processing"
        batch_info["job_id"] = core_response.get("job_id")
        
        return FinalizeBatchResponse(
            job_id=core_response.get("job_id"),
            status="accepted"
        )
    except Exception as e:
        logger.error(f"Failed to finalize batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))
