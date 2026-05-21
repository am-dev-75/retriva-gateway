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

router = APIRouter(prefix="/kbs", tags=["kbs"])

import re
import uuid
from loguru import logger
from retriva_gateway.core.client import core_client

class KnowledgeBase(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    document_count: int = 0
    status: str = "active"

class KBCreate(BaseModel):
    name: str
    description: Optional[str] = None

# In-memory mock storage
_kbs: Dict[str, KnowledgeBase] = {
    "default": KnowledgeBase(
        id="default",
        name="default",
        description="Default Knowledge Base",
        document_count=0,
        status="active"
    )
}

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text).strip('-')
    return text

@router.get("", response_model=List[KnowledgeBase])
async def list_kbs():
    kbs = list(_kbs.values())
    for kb in kbs:
        try:
            payload = {
                "query": "",
                "kb_ids": [kb.id],
                "limit": 1,
                "is_discovery": True
            }
            res = await core_client.search_documents(payload)
            kb.document_count = res.get("total", 0)
        except Exception as e:
            logger.warning(f"Failed to fetch document count for KB {kb.id}: {e}")
    return kbs

@router.post("", response_model=KnowledgeBase)
async def create_kb(kb_in: KBCreate):
    kb_id = slugify(kb_in.name)
    if not kb_id:
        kb_id = str(uuid.uuid4())[:8]
    if kb_id in _kbs:
        kb_id = f"{kb_id}-{str(uuid.uuid4())[:6]}"
    
    new_kb = KnowledgeBase(
        id=kb_id,
        name=kb_in.name,
        description=kb_in.description,
        document_count=0,
        status="active"
    )
    _kbs[kb_id] = new_kb
    return new_kb

@router.get("/{kb_id}", response_model=KnowledgeBase)
async def get_kb(kb_id: str):
    if kb_id in _kbs:
        kb = _kbs[kb_id]
        try:
            payload = {
                "query": "",
                "kb_ids": [kb.id],
                "limit": 1,
                "is_discovery": True
            }
            res = await core_client.search_documents(payload)
            kb.document_count = res.get("total", 0)
        except Exception as e:
            logger.warning(f"Failed to fetch document count for KB {kb_id}: {e}")
        return kb
    raise HTTPException(status_code=404, detail="Knowledge Base not found")

@router.patch("/{kb_id}", response_model=KnowledgeBase)
async def update_kb(kb_id: str, kb_in: KBCreate):
    if kb_id not in _kbs:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    kb = _kbs[kb_id]
    kb.name = kb_in.name
    if kb_in.description is not None:
        kb.description = kb_in.description
    return kb

@router.delete("/{kb_id}")
async def delete_kb(kb_id: str):
    if kb_id in _kbs:
        del _kbs[kb_id]
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Knowledge Base not found")
