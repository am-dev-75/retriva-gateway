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

from fastapi import APIRouter, HTTPException, Request
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from retriva_gateway.core.client import core_client
from retriva_gateway.core.filters import FilterManager
import json

from retriva_gateway.core.models import SearchRequest, MetadataFilterMode
from retriva_gateway.core.context import get_correlation_id
from loguru import logger

router = APIRouter(prefix="/documents", tags=["documents"])

class Document(BaseModel):
    id: str
    name: str
    kb_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

@router.get("")
async def list_documents(
    request: Request,
    metadata_filter_mode: MetadataFilterMode = MetadataFilterMode.HARD
):
    """Proxy Core document listing with metadata normalization."""
    corr_id = get_correlation_id() or "unknown"
    try:
        mode = FilterManager.validate_mode(metadata_filter_mode)
    except ValueError as e:
        logger.error(f"[{corr_id}] Invalid metadata_filter_mode: {metadata_filter_mode}")
        raise HTTPException(status_code=400, detail=str(e))

    # Extract query params that are not 'metadata_filter_mode'
    filters = {k: v for k, v in request.query_params.items() if k != "metadata_filter_mode"}
    # Normalize filters for Core v2
    try:
        normalized_filters = await FilterManager.normalize_v2(filters)
    except ValueError as e:
        logger.error(f"[{corr_id}] Filter normalization failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    
    search_payload = {
        "query": "",
        "metadata_filters": normalized_filters,
        "metadata_filter_mode": mode,
        "limit": 100
    }
    logger.info(f"[{corr_id}] Discovery routing: list documents. mode={mode}, filters={normalized_filters}")
    return await core_client.search_documents(search_payload)

@router.get("/count")
async def count_documents(
    request: Request,
    metadata_filter_mode: MetadataFilterMode = MetadataFilterMode.HARD
):
    """Proxy Core document counting with metadata normalization."""
    corr_id = get_correlation_id() or "unknown"
    try:
        mode = FilterManager.validate_mode(metadata_filter_mode)
    except ValueError as e:
        logger.error(f"[{corr_id}] Invalid metadata_filter_mode: {metadata_filter_mode}")
        raise HTTPException(status_code=400, detail=str(e))

    filters = {k: v for k, v in request.query_params.items() if k != "metadata_filter_mode"}
    try:
        normalized_filters = await FilterManager.normalize_v2(filters)
    except ValueError as e:
        logger.error(f"[{corr_id}] Filter normalization failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    
    search_payload = {
        "query": "",
        "metadata_filters": normalized_filters,
        "metadata_filter_mode": mode,
        "limit": 1
    }
    logger.info(f"[{corr_id}] Discovery routing: count documents. mode={mode}, filters={normalized_filters}")
    result = await core_client.search_documents(search_payload)
    return {"count": result.get("total", 0)}

@router.post("/search")
async def search_documents(request: SearchRequest):
    """Proxy Core document search (discovery mode).

    In discovery mode, ``metadata_filter_mode`` is not meaningful — tags
    are always applied as strict filters.  Only the query (filename glob),
    metadata_filters (tags), kb_ids, and case_sensitive flag are forwarded.
    """
    corr_id = get_correlation_id() or "unknown"
    
    # Priority: metadata_filters (list) > filters (dict)
    filters = request.metadata_filters or request.filters or {}

    query = request.query
    limit = request.limit
    try:
        normalized_filters = await FilterManager.normalize_v2(filters)
    except ValueError as e:
        logger.error(f"[{corr_id}] Filter normalization failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    
    search_payload = {
        "query": query,
        "kb_ids": request.kb_ids,
        "metadata_filters": normalized_filters,
        "limit": limit,
        "is_discovery": True,
        "case_sensitive": request.case_sensitive
    }
    
    logger.info(f"[{corr_id}] Discovery routing: search documents. query='{query}', filters={normalized_filters}")
    return await core_client.search_documents(search_payload)

@router.post("/filter")
async def filter_documents(request: SearchRequest):
    """Proxy Core document filtering via POST (now redirects to search)."""
    return await search_documents(request)

@router.get("/{doc_id}")
async def get_document(doc_id: str):
    """Proxy Core document retrieval."""
    return await core_client.get_document(doc_id)

@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    """Proxy Core document deletion."""
    return await core_client.delete_document(doc_id)
