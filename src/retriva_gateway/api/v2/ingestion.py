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
from pydantic import BaseModel, field_validator
from retriva_gateway.core.client import core_client
from loguru import logger
import json
import os
import re
import base64
from pathlib import Path
from urllib.parse import urlparse
import httpx
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
    user_metadata: Optional[str] = Form(None),
    kb_id: str = Form("default"),
    force: bool = Form(False),
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
                "user_metadata": json.dumps(merged_metadata),
                "kb_id": kb_id,
                "force": str(force).lower(),
            }
        )
        
        # Track file in batch
        status_val = "accepted"
        if not core_response.get("job_id") and core_response.get("status") == "already_exists":
            status_val = "completed"
            
        file_info = {
            "filename": file.filename,
            "source_path": source_path,
            "job_id": core_response.get("job_id"),
            "status": status_val
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


# ---------------------------------------------------------------------------
# URL fetch proxy — single-page, non-recursive
# ---------------------------------------------------------------------------

class FetchUrlRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("url must not be empty")
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("url must use http or https scheme")
        if not parsed.netloc:
            raise ValueError("url must include a host")
        return v


class FetchUrlResponse(BaseModel):
    url: str
    final_url: str
    content: str
    content_type: str
    title: str = ""
    is_binary: bool = False
    filename: str = ""


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# Content types that are text-based and can be returned as decoded strings.
_TEXT_CONTENT_PREFIXES = ("text/", "application/json", "application/xml", "application/javascript")
_TEXT_CONTENT_KEYWORDS = ("html", "xml", "json", "javascript")


def _is_text_content(content_type: str) -> bool:
    ct = content_type.lower()
    if any(ct.startswith(p) for p in _TEXT_CONTENT_PREFIXES):
        return True
    if any(kw in ct for kw in _TEXT_CONTENT_KEYWORDS):
        return True
    return False


def _extract_title(html: str) -> str:
    m = _TITLE_RE.search(html)
    if m:
        return m.group(1).strip()
    return ""


def _extension_for_content_type(content_type: str) -> str:
    """Return a sensible file extension for common content types."""
    ct = content_type.lower().split(";")[0].strip()
    mapping = {
        "text/html": ".html",
        "application/xhtml+xml": ".html",
        "text/plain": ".txt",
        "text/markdown": ".md",
        "application/json": ".json",
        "application/xml": ".xml",
        "text/xml": ".xml",
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "image/tiff": ".tiff",
        "image/bmp": ".bmp",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.ms-powerpoint": ".ppt",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/rtf": ".rtf",
    }
    return mapping.get(ct, "")


def _filename_from_url(final_url: str, title: str, content_type: str) -> str:
    """Build a filename from the URL path, page title, or content type."""
    ext = _extension_for_content_type(content_type)

    # Try to extract a filename from the URL path
    parsed = urlparse(final_url)
    path_name = os.path.basename(parsed.path)
    if path_name:
        # Strip query string and fragments, keep the base name
        base, existing_ext = os.path.splitext(path_name)
        if base and existing_ext:
            return path_name
        if base:
            return base + ext

    # Fall back to the page title (sanitized)
    if title:
        sanitized = re.sub(r"[^a-zA-Z0-9_\- ]", "", title).strip().replace(" ", "_")
        if sanitized:
            return sanitized + ext

    return "downloaded" + ext


@router.post("/fetch-url", response_model=FetchUrlResponse)
async def fetch_url(request: FetchUrlRequest):
    """Fetch a single web resource (page or file) and return its content.

    This is a non-recursive fetch: only the requested URL is downloaded.
    The returned content can then be submitted through the standard batch
    upload flow (``/ingestion/batches/{id}/files``) for ingestion.

    Text-based content (HTML, plain text, XML, JSON) is returned as a
    decoded string in ``content``.  Binary content (PDF, images, Office
    documents) is returned as a base64-encoded string in ``content`` with
    ``is_binary=True``; the client must decode it before constructing a
    ``File`` object.
    """
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            response = await client.get(
                request.url,
                headers={
                    "User-Agent": "Retriva/1.0 (URL Ingestion Proxy)",
                    "Accept": "*/*",
                },
            )
            response.raise_for_status()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timed out fetching the requested URL")
    except httpx.HTTPError as e:
        logger.warning(f"fetch-url failed for {request.url}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {e}")

    content_type = response.headers.get("content-type", "application/octet-stream")
    # Strip charset etc. for the is_binary check, but pass the full header to the client
    ct_main = content_type.split(";")[0].strip()
    is_binary = not _is_text_content(ct_main)

    title = ""
    if not is_binary:
        text = response.text
        title = _extract_title(text)
        content = text
    else:
        content = base64.b64encode(response.content).decode("ascii")

    final_url = str(response.url)
    filename = _filename_from_url(final_url, title, ct_main)

    return FetchUrlResponse(
        url=request.url,
        final_url=final_url,
        content=content,
        content_type=content_type,
        title=title,
        is_binary=is_binary,
        filename=filename,
    )
