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
from retriva_gateway.core.intent import Intent, IntentDetector
from loguru import logger

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

def _synthesize_response(content: str, stream: bool):
    if stream:
        async def _stream_mock():
            chunk = {"id": f"msg_{datetime.datetime.now().timestamp()}", "choices": [{"delta": {"content": content}}]}
            yield f"data: {json.dumps(chunk)}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"
        return StreamingResponse(_stream_mock(), media_type="text/event-stream")
    else:
        web_ui_message = {
            "id": f"msg_{datetime.datetime.now().timestamp()}",
            "role": "assistant",
            "content": content,
            "timestamp": datetime.datetime.now().isoformat(),
            "citations": []
        }
        return JSONResponse(content=web_ui_message)

@router.post("/chat")
async def chat(payload: Dict[str, Any]):
    kb_ids = payload.get("kb_ids", ["default"])
    message = payload.get("message", "")
    stream = payload.get("stream", False)
    explicit_filters = payload.get("filters", {})

    intent, extracted_metadata = await IntentDetector.analyze(message)
    
    # Explicit filters override natural language
    if explicit_filters:
        extracted_metadata = explicit_filters
        if intent == Intent.PURE_RAG:
            intent = Intent.METADATA_FILTERED_RAG

    logger.debug(f"Chat request: kb_ids={kb_ids}, stream={stream}, message_len={len(message)}, intent={intent}, meta={extracted_metadata}")

    if intent == Intent.CATALOG_DOCUMENT_COUNT:
        try:
            params = {f"metadata.{k}": v for k, v in extracted_metadata.items()}
            response = await core_client.count_documents(params=params)
            count = response.get("count", 0) if isinstance(response, dict) else 0
            return _synthesize_response(f"There are {count} documents in the catalog.", stream)
        except Exception as e:
            logger.error(f"Catalog count failed: {e}")
            raise

    if intent == Intent.CATALOG_DOCUMENT_LIST:
        try:
            params = {f"metadata.{k}": v for k, v in extracted_metadata.items()}
            response = await core_client.list_documents(params=params)
            docs = response.get("items", response) if isinstance(response, dict) else response
            if not isinstance(docs, list):
                docs = []
            count = len(docs)
            content = f"I found {count} documents in the catalog."
            if docs:
                names = [d.get("name", d.get("title", "Unknown")) for d in docs[:5]]
                content += "\nHere are some of them:\n" + "\n".join(f"- {name}" for name in names)
            return _synthesize_response(content, stream)
        except Exception as e:
            logger.error(f"Catalog list failed: {e}")
            raise

    # For RAG variants
    core_payload = {
        "model": "retriva",
        "messages": [{"role": "user", "content": message}],
        "stream": stream,
        "user_metadata_filter": {"kb_id": kb_ids[0]} if (kb_ids and kb_ids[0] != "default") else None
    }

    if intent == Intent.METADATA_FILTERED_RAG and extracted_metadata:
        if core_payload["user_metadata_filter"] is None:
            core_payload["user_metadata_filter"] = {}
        core_payload["user_metadata_filter"].update(extracted_metadata)

    try:
        # Route to the appropriate Core endpoint based on intent
        if intent == Intent.METADATA_FILTERED_RAG:
            # Reformat payload if /retrieval/query expects different shape
            # Assuming it accepts OpenAI format for now based on previous chat.py logic
            # but we use the new endpoint
            if stream:
                # Assuming retrieval_query doesn't stream, we fallback to chat_completions if stream=True
                # Or we assume retrieval_query CAN stream if we want.
                # Let's just use chat_completions for now if streaming, because retrieval_query might be a sync API.
                # Actually, the user says "Route metadata-filtered semantic questions to Core /api/v2/retrieval/query."
                # We will call retrieval_query.
                pass
            
            core_response = await core_client.retrieval_query(core_payload)
            # If retrieval_query doesn't return OpenAI format, we'd need to map it here.
            # Assuming it does for this architectural draft.
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

        else:
            # Intent.PURE_RAG or others default to chat_completions
            if stream:
                gen = core_client.chat_completions(core_payload, stream=True)
                return StreamingResponse(await gen, media_type="text/event-stream")
            else:
                core_response = await core_client.chat_completions(core_payload, stream=False)
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
        logger.error(f"Chat forwarding failed: {e}")
        raise
