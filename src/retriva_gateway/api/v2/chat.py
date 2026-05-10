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

router = APIRouter(tags=["chat"])

@router.post("/chat")
async def chat(payload: Dict[str, Any]):
    """
    Facade for Retriva Core chat completion.
    Forwarding the request and handling streaming if needed.
    """
    stream = payload.get("stream", False)
    
    try:
        if stream:
            gen = core_client.chat_completions(payload, stream=True)
            return StreamingResponse(
                await gen,
                media_type="text/event-stream"
            )
        else:
            response = await core_client.chat_completions(payload, stream=False)
            return JSONResponse(content=response)
    except Exception as e:
        logger.error(f"Chat forwarding failed: {e}")
        raise
