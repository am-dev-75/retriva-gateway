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

from fastapi import APIRouter, Request, HTTPException
from retriva_gateway.core.client import core_client
from retriva_gateway.core.context import get_correlation_id
from loguru import logger

router = APIRouter(prefix="/metadata", tags=["metadata"])

@router.get("/schema")
async def get_metadata_schema():
    """Proxy Core metadata schema endpoint."""
    corr_id = get_correlation_id() or "unknown"
    logger.info(f"[{corr_id}] Get metadata schema")
    return await core_client.get_metadata_schema()

@router.get("/values")
async def get_metadata_values(request: Request):
    """Proxy Core metadata values endpoint."""
    corr_id = get_correlation_id() or "unknown"
    key = request.query_params.get("key")
    if not key:
        logger.error(f"[{corr_id}] Missing 'key' query parameter in get_metadata_values")
        raise HTTPException(status_code=400, detail="Missing 'key' query parameter")
    
    logger.info(f"[{corr_id}] Get metadata values for key: {key}")
    return await core_client.get_metadata_values(key)

@router.get("/{field}/values")
async def get_metadata_values_compat(field: str):
    """Legacy/Compat proxy for field values."""
    corr_id = get_correlation_id() or "unknown"
    logger.info(f"[{corr_id}] Get metadata values (compat) for field: {field}")
    return await core_client.get_metadata_values(field)
