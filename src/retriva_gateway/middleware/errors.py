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

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from retriva_gateway.core.models import ErrorResponse, ErrorDetail
from loguru import logger
import httpx

async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="HTTP_ERROR",
                    message=exc.detail,
                    details={"status_code": exc.status_code}
                )
            ).model_dump()
        )
    
    if isinstance(exc, httpx.HTTPStatusError):
        logger.error(f"Core API error: {exc.response.status_code} - {exc.response.text}")
        # Try to parse Core error if it follows a similar pattern
        try:
            core_error = exc.response.json()
            message = core_error.get("detail") or core_error.get("error", {}).get("message") or str(exc)
        except:
            message = str(exc)
            
        return JSONResponse(
            status_code=exc.response.status_code,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="CORE_ERROR",
                    message=message,
                    details={"core_status": exc.response.status_code}
                )
            ).model_dump()
        )

    logger.exception("Unhandled exception occurred")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=ErrorDetail(
                code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred.",
                details={}
            )
        ).model_dump()
    )
