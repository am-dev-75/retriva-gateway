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

import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from retriva_gateway.core.context import correlation_id_ctx
from loguru import logger

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        token = correlation_id_ctx.set(correlation_id)
        
        # Add correlation ID to loguru extra
        with logger.contextualize(correlation_id=correlation_id):
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            correlation_id_ctx.reset(token)
            return response
