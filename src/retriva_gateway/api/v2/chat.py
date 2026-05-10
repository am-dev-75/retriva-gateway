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
from loguru import logger
from typing import Any, Dict
import datetime

router = APIRouter(tags=["chat"])


def _transform_citations(core_sources: list) -> list:
    """Transform Core Citation objects into the flat WebUI Citation shape.

    Core returns:  {source: {name: "..."}, document: [...], metadata: [{source: "url", title: "..."}]}
    WebUI expects: {id: "1", document_id: "url", filename: "Title", text: "snippet"}
    """
    citations = []
    for idx, src in enumerate(core_sources):
        name = src.get("source", {}).get("name", "Unknown")
        doc_snippets = src.get("document", [])
        meta_list = src.get("metadata", [])
        doc_id = meta_list[0].get("source", "") if meta_list else ""
        text = "\n".join(doc_snippets)[:500]  # Truncate for UI display
        citations.append({
            "id": str(idx + 1),
            "document_id": doc_id,
            "filename": name,
            "text": text,
        })
    return citations


@router.post("/chat")
async def chat(payload: Dict[str, Any]):
    """
    Facade for Retriva Core chat completion.
    Translates WebUI payload to Retriva Core format and back.
    """
    kb_ids = payload.get("kb_ids", ["default"])
    message = payload.get("message", "")
    stream = payload.get("stream", False)

    logger.debug(f"Chat request: kb_ids={kb_ids}, stream={stream}, message_len={len(message)}")

    core_payload = {
        "model": "retriva",
        "messages": [
            {"role": "user", "content": message}
        ],
        "stream": stream,
        # Map the first KB ID to user_metadata_filter for Core alignment
        # We treat 'default' as unfiltered to support legacy/untagged data
        "user_metadata_filter": {"kb_id": kb_ids[0]} if (kb_ids and kb_ids[0] != "default") else None
    }

    try:
        if stream:
            gen = core_client.chat_completions(core_payload, stream=True)
            return StreamingResponse(
                await gen,
                media_type="text/event-stream"
            )
        else:
            core_response = await core_client.chat_completions(core_payload, stream=False)
            logger.debug(f"Core response keys: {list(core_response.keys())}")

            # Extract content from OpenAI-compatible response
            choice = core_response.get("choices", [{}])[0]
            choice_message = choice.get("message", {})

            # Transform Core sources into WebUI Citation shape
            raw_sources = core_response.get("sources", [])
            citations = _transform_citations(raw_sources)

            # Build the simplified message for the WebUI
            web_ui_message = {
                "id": core_response.get("id", f"msg_{datetime.datetime.now().timestamp()}"),
                "role": "assistant",
                "content": choice_message.get("content", ""),
                "timestamp": datetime.datetime.now().isoformat(),
                "citations": citations
            }

            return JSONResponse(content=web_ui_message)
    except Exception as e:
        logger.error(f"Chat forwarding failed: {e}")
        raise
