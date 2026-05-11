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

router = APIRouter(prefix="/metadata", tags=["metadata"])

@router.get("/schema")
async def get_metadata_schema():
    """Proxy Core metadata schema endpoint."""
    return await core_client.get_metadata_schema()

@router.get("/values")
async def get_metadata_values(request: Request):
    """Proxy Core metadata values endpoint."""
    key = request.query_params.get("key")
    if not key:
        raise HTTPException(status_code=400, detail="Missing 'key' query parameter")
    return await core_client.get_metadata_values(key)

@router.get("/{field}/values")
async def get_metadata_values_compat(field: str):
    """Legacy/Compat proxy for field values."""
    return await core_client.get_metadata_values(field)
