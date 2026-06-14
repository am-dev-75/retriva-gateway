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
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from retriva_gateway.api.router import api_router, api_v2_router, stt_router
from retriva_gateway.config import settings
from retriva_gateway.middleware.correlation import CorrelationIdMiddleware
from retriva_gateway.middleware.errors import global_exception_handler
import httpx
from loguru import logger
import sys

# Configure loguru and intercept standard logging
import logging

class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

logger.remove()
logger.add(sys.stdout, format="<green>[{time:YYYYMMDD HH:mm:ss}]</green> [<level>{level}</level>] <level>{message}</level>", level=settings.LOG_LEVEL)

def _intercept_uvicorn_logging():
    """Replace uvicorn's logging handlers with our InterceptHandler.
    
    Must be called AFTER uvicorn has finished its own logging setup,
    otherwise uvicorn overwrites our handlers during startup.
    """
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.asgi", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = [InterceptHandler()]
        uv_logger.propagate = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Intercept uvicorn loggers now that uvicorn has fully initialised
    _intercept_uvicorn_logging()

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
    logger.info(f"STT_ENABLED: {settings.STT_ENABLED}")
    if settings.STT_ENABLED:
        logger.info(f"WHISPER_SERVER_URL: {settings.WHISPER_SERVER_URL}")
        logger.info(f"STT_MAX_AUDIO_BYTES: {settings.STT_MAX_AUDIO_BYTES}")
        logger.info(f"STT_REQUEST_TIMEOUT_SECONDS: {settings.STT_REQUEST_TIMEOUT_SECONDS}")
    logger.info("---------------------")
    
    yield
    
    logger.info("Retriva Gateway shutting down...")

app = FastAPI(
    title="Retriva Gateway",
    version="0.1.0",
    description="Backend-for-Frontend for Retriva WebUI",
    lifespan=lifespan
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
app.include_router(api_v2_router)
app.include_router(stt_router)  # Root-level: POST /stt/transcribe, GET /stt/health


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.GATEWAY_HOST, port=settings.GATEWAY_PORT, log_config=None)
