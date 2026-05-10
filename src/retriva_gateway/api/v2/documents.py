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

from fastapi import APIRouter, HTTPException
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from retriva_gateway.core.client import core_client

router = APIRouter(prefix="/documents", tags=["documents"])

class Document(BaseModel):
    id: str
    name: str
    kb_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

@router.get("", response_model=List[Document])
async def list_documents(kb_id: Optional[str] = None):
    # Placeholder for document listing
    # Since Core doesn't have a list endpoint yet, we return an empty list
    return []

@router.get("/{doc_id}", response_model=Document)
async def get_document(doc_id: str):
    # This could call Core v2 /api/v2/documents/{doc_id} if it existed
    # For now, placeholder
    raise HTTPException(status_code=404, detail="Document not found")

@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    try:
        await core_client.delete_document(doc_id)
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
