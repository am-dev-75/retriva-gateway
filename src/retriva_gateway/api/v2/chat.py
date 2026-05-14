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

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse
from retriva_gateway.core.client import core_client
from retriva_gateway.core.filters import FilterManager
from loguru import logger
from typing import Any, Dict
import datetime
import json

from retriva_gateway.core.models import ChatRequest
from retriva_gateway.core.context import get_correlation_id

router = APIRouter(tags=["chat"])

def _transform_citations(core_sources: list) -> list:
    citations = []
    for idx, src in enumerate(core_sources):
        name = src.get("source", {}).get("name", "Unknown")
        doc_snippets = src.get("document", [])
        meta_list = src.get("metadata", [])
        doc_id = meta_list[0].get("source", "") if meta_list else ""
        text = "\n".join(doc_snippets)[:500]
        citations.append({
            "id": str(idx + 1),
            "document_id": doc_id,
            "filename": name,
            "text": text,
        })
    return citations


@router.post("/chat")
async def chat(request: ChatRequest):
    corr_id = get_correlation_id() or "unknown"
    kb_ids = request.kb_ids
    message = request.message
    stream = request.stream
    
    # Priority: metadata_filters (list) > filters (dict)
    explicit_filters = request.metadata_filters or request.filters or []
    mode = request.metadata_filter_mode

    try:
        metadata_filter_mode = FilterManager.validate_mode(mode)
    except ValueError as e:
        logger.error(f"[{corr_id}] Invalid metadata_filter_mode: {mode}")
        return JSONResponse(status_code=400, content={"detail": str(e)})

    # As per SDD architectural revision: No inference. 
    # Use explicit filters provided by the UI only.
    try:
        normalized_filters = await FilterManager.normalize_v2(explicit_filters)
    except ValueError as e:
        logger.error(f"[{corr_id}] Filter normalization failed: {e}")
        return JSONResponse(status_code=400, content={"detail": str(e)})
    
    core_payload = {
        "query": message,
        "kb_ids": kb_ids,
        "metadata_filters": normalized_filters,
        "metadata_filter_mode": metadata_filter_mode,
        "stream": stream
    }

    logger.info(f"[{corr_id}] Chat routing: direct RAG. mode={metadata_filter_mode}, filters={normalized_filters}")

    try:
        if stream:
            gen = await core_client.retrieval_query(core_payload, stream=True)
            return StreamingResponse(gen, media_type="text/event-stream")
        else:
            core_response = await core_client.retrieval_query(core_payload, stream=False)
            choice = core_response.get("choices", [{}])[0]
            choice_message = choice.get("message", {})
            raw_sources = core_response.get("sources", [])
            citations = _transform_citations(raw_sources)
            
            web_ui_message = {
                "id": core_response.get("id", f"msg_{datetime.datetime.now().timestamp()}"),
                "role": "assistant",
                "content": choice_message.get("content", ""),
                "timestamp": datetime.datetime.now().isoformat(),
                "citations": citations
            }
            return JSONResponse(content=web_ui_message)
    except Exception as e:
        logger.error(f"[{corr_id}] Chat forwarding failed: {e}")
        raise
