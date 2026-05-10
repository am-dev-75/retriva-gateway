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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from retriva_gateway.api.router import api_router
from retriva_gateway.config import settings
from retriva_gateway.middleware.correlation import CorrelationIdMiddleware
from retriva_gateway.middleware.errors import global_exception_handler
import httpx
from loguru import logger
import sys

# Configure loguru
logger.remove()
logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:7}</level> - <level>{message}</level>", level=settings.LOG_LEVEL)

app = FastAPI(
    title="Retriva Gateway",
    version="0.1.0",
    description="Backend-for-Frontend for Retriva WebUI"
)

# Exception handlers
from fastapi import HTTPException as FastAPIHTTPException
app.add_exception_handler(FastAPIHTTPException, global_exception_handler)
app.add_exception_handler(httpx.HTTPStatusError, global_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Middlewares
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.GATEWAY_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(api_router)

@app.on_event("startup")
async def startup_event():
    logger.info("Retriva Gateway starting up...")
    logger.info("--- Configuration ---")
    logger.info(f"GATEWAY_HOST: {settings.GATEWAY_HOST}")
    logger.info(f"GATEWAY_PORT: {settings.GATEWAY_PORT}")
    logger.info(f"RETRIVA_CORE_INGESTION_URL: {settings.RETRIVA_CORE_INGESTION_URL}")
    logger.info(f"RETRIVA_CORE_CHAT_URL: {settings.RETRIVA_CORE_CHAT_URL}")
    logger.info(f"GATEWAY_ENABLE_AUTH: {settings.GATEWAY_ENABLE_AUTH}")
    logger.info(f"GATEWAY_ENABLE_ARTIFACTS: {settings.GATEWAY_ENABLE_ARTIFACTS}")
    logger.info(f"GATEWAY_ENABLE_FOLDER_UPLOAD: {settings.GATEWAY_ENABLE_FOLDER_UPLOAD}")
    logger.info(f"GATEWAY_ENABLE_SPEECH_INPUT: {settings.GATEWAY_ENABLE_SPEECH_INPUT}")
    logger.info(f"GATEWAY_MAX_UPLOAD_MB: {settings.GATEWAY_MAX_UPLOAD_MB}")
    logger.info(f"GATEWAY_UPLOAD_TMP_DIR: {settings.GATEWAY_UPLOAD_TMP_DIR}")
    logger.info(f"GATEWAY_CORS_ORIGINS: {settings.GATEWAY_CORS_ORIGINS}")
    logger.info(f"LOG_LEVEL: {settings.LOG_LEVEL}")
    logger.info("---------------------")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Retriva Gateway shutting down...")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.GATEWAY_HOST, port=settings.GATEWAY_PORT)
