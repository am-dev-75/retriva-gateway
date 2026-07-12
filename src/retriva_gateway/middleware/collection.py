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

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from retriva_gateway.core.context import get_principal, active_collection_ctx
from retriva_gateway.core.collection_resolver import resolve_active_collection
from retriva_gateway.config import settings
from loguru import logger

class CollectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        principal = get_principal()
        
        # Check if the client requested a specific collection
        requested = request.headers.get("X-Retriva-Requested-Collection")
        
        try:
            active_collection = resolve_active_collection(
                principal=principal,
                requested_collection=requested,
                default_fallback=settings.RETRIVA_DEFAULT_COLLECTION
            )
        except Exception as e:
            # We let the resolver raise HTTPExceptions (400 or 403) and 
            # let FastAPI handle them, but if we're deeply nested in 
            # middleware, Starlette might catch it differently.
            # Assuming FastAPI handles exceptions raised in middleware.
            raise
            
        token = active_collection_ctx.set(active_collection)
        
        try:
            return await call_next(request)
        finally:
            active_collection_ctx.reset(token)
