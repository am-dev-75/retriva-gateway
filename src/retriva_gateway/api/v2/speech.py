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

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status
from retriva_gateway.config import settings
from retriva_gateway.core.whisper_client import whisper_client
from retriva_gateway.core.models import TranscribeResponse
from loguru import logger

router = APIRouter(prefix="/stt", tags=["stt"])


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    file: UploadFile = File(...),
    language: str = Form("auto"),
    prompt: str = Form(""),
):
    """
    Proxy endpoint for speech-to-text via whisper.cpp.

    Accepts a browser-recorded audio file (typically audio/webm or audio/wav),
    forwards it to the configured whisper-server, and returns the normalized
    transcript.
    """
    # --- Feature gate ---
    if not settings.STT_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Speech-to-text is not enabled on this Gateway instance.",
        )

    # --- Read and validate file ---
    file_content = await file.read()

    if len(file_content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded audio file is empty.",
        )

    if len(file_content) > settings.STT_MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Audio file exceeds maximum allowed size "
                f"({settings.STT_MAX_AUDIO_BYTES} bytes)."
            ),
        )

    logger.debug(
        "STT request received: filename={} size={} content_type={}",
        file.filename,
        len(file_content),
        file.content_type,
    )

    # --- Forward to whisper-server ---
    text = await whisper_client.transcribe(
        file_content=file_content,
        filename=file.filename or "audio",
        content_type=file.content_type or "application/octet-stream",
        language=language if language and language != "auto" else None,
        prompt=prompt if prompt else None,
    )

    return TranscribeResponse(
        text=text,
        language=language,
    )


@router.get("/health")
async def stt_health():
    """Report STT feature status without actively probing whisper-server."""
    return {
        "enabled": settings.STT_ENABLED,
        "whisper_url_configured": bool(settings.WHISPER_SERVER_URL),
    }

