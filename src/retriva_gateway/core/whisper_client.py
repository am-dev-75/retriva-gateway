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

import httpx
from fastapi import HTTPException, status
from retriva_gateway.config import settings
from retriva_gateway.core.context import get_correlation_id
from loguru import logger
from typing import Optional


def extract_transcript_from_whisper_response(response: httpx.Response) -> str:
    """Extract transcript text from a whisper.cpp HTTP response.

    Uses the ``content-type`` header to decide whether to parse JSON or
    fall back to plain text.  Tolerates multiple JSON shapes produced by
    different whisper-server builds:

    1. ``{"text": "hello"}``
    2. ``{"transcription": "hello"}``
    3. ``{"segments": [{"text": "hello"}, ...]}``
    4. Plain text (non-JSON content-type or JSON parse failure)

    Returns the stripped transcript string, or empty string if nothing
    can be extracted.
    """
    content_type = response.headers.get("content-type", "")

    text = ""

    if "application/json" in content_type:
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            if isinstance(payload.get("text"), str):
                text = payload["text"].strip()
            elif isinstance(payload.get("transcription"), str):
                text = payload["transcription"].strip()
            elif isinstance(payload.get("segments"), list):
                parts = []
                for segment in payload["segments"]:
                    if isinstance(segment, dict) and isinstance(segment.get("text"), str):
                        part = segment["text"].strip()
                        if part:
                            parts.append(part)
                text = " ".join(parts).strip()

    if not text:
        text = response.text.strip()

    return text


# Keep the old string-based normalizer for unit-testing convenience.
# The integration path uses extract_transcript_from_whisper_response().
def normalize_whisper_response(response_text: str) -> Optional[str]:
    """Extract transcript from raw response text (string-based variant).

    Kept for unit tests that don't have a full httpx.Response object.
    """
    import json

    raw = response_text.strip()
    if not raw:
        return None

    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw

    if isinstance(body, dict):
        if "text" in body and isinstance(body["text"], str):
            text = body["text"].strip()
            if text:
                return text
        if "transcription" in body and isinstance(body["transcription"], str):
            text = body["transcription"].strip()
            if text:
                return text
        segments = body.get("segments")
        if isinstance(segments, list) and segments:
            parts = []
            for seg in segments:
                if isinstance(seg, dict) and "text" in seg:
                    parts.append(str(seg["text"]).strip())
            joined = " ".join(p for p in parts if p)
            if joined:
                return joined

    return None


import subprocess

def _convert_to_wav(audio_bytes: bytes) -> bytes:
    """Convert arbitrary audio bytes to 16kHz 1-channel WAV using ffmpeg."""
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-i", "pipe:0",
                "-ar", "16000",
                "-ac", "1",
                "-c:a", "pcm_s16le",
                "-f", "wav",
                "pipe:1"
            ],
            input=audio_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
        return proc.stdout
    except subprocess.CalledProcessError as e:
        logger.error("ffmpeg conversion failed: {}", e.stderr.decode("utf-8", errors="ignore"))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Audio conversion failed.")
    except FileNotFoundError:
        logger.error("ffmpeg not found on the system.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ffmpeg not installed.")

class WhisperClient:
    """HTTP client for whisper.cpp whisper-server /inference endpoint."""

    def _get_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        correlation_id = get_correlation_id()
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        return headers

    async def transcribe(
        self,
        file_content: bytes,
        filename: str,
        content_type: str,
        language: str | None = None,
        prompt: str | None = None,
    ) -> str:
        """Forward audio to whisper-server and return the transcribed text.

        Raises:
            HTTPException: 504 on timeout, 502 on connection error / bad
                           upstream response / malformed whisper output.
        """
        timeout = httpx.Timeout(
            float(settings.STT_REQUEST_TIMEOUT_SECONDS),
            connect=10.0,
        )

        # Transcode audio to WAV required by whisper.cpp
        wav_bytes = _convert_to_wav(file_content)

        # Build multipart form fields
        files = {"file": ("query.wav", wav_bytes, "audio/wav")}
        # whisper.cpp whisper-server accepts "response_format" to request
        # JSON output instead of plain text.
        data: dict[str, str] = {"response_format": "json"}

        if language and language != "auto":
            data["language"] = language
        if prompt:
            data["prompt"] = prompt

        logger.debug(
            "Forwarding audio to whisper-server: url={} size={} content_type={} language={} prompt_len={}",
            settings.WHISPER_SERVER_URL,
            len(file_content),
            content_type,
            language,
            len(prompt) if prompt else 0,
        )

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    settings.WHISPER_SERVER_URL,
                    files=files,
                    data=data,
                    headers=self._get_headers(),
                )
                response.raise_for_status()
        except httpx.TimeoutException:
            logger.warning("Whisper-server request timed out")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Whisper server did not respond in time.",
            )
        except httpx.ConnectError:
            logger.warning("Could not connect to whisper-server at {}", settings.WHISPER_SERVER_URL)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Whisper server is unavailable.",
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Whisper-server returned non-2xx: status={} body={}",
                exc.response.status_code,
                exc.response.text[:500],
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Whisper server error (HTTP {exc.response.status_code}).",
            )

        # Parse and normalize using content-type-aware extractor
        text = extract_transcript_from_whisper_response(response)

        if not text:
            logger.warning("Could not extract transcript from whisper response: {}", response.text[:500])
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Whisper server returned a malformed response.",
            )

        return text


whisper_client = WhisperClient()


