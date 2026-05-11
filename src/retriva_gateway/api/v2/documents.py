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

router = APIRouter(prefix="/documents", tags=["documents"])

class Document(BaseModel):
    id: str
    name: str
    kb_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

@router.get("")
async def list_documents(request: Request):
    """Proxy Core document listing."""
    return await core_client.list_documents(params=request.query_params)

@router.get("/count")
async def count_documents(request: Request):
    """Proxy Core document counting."""
    return await core_client.count_documents(params=request.query_params)

@router.post("/filter")
async def filter_documents(payload: Dict[str, Any]):
    """Proxy Core document filtering via POST."""
    return await core_client.filter_documents(payload)

@router.get("/{doc_id}")
async def get_document(doc_id: str):
    """Proxy Core document retrieval."""
    return await core_client.get_document(doc_id)

@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    """Proxy Core document deletion."""
    return await core_client.delete_document(doc_id)
