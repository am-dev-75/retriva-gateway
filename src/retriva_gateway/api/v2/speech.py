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

from fastapi import APIRouter, HTTPException, status
from retriva_gateway.config import settings

router = APIRouter(prefix="/speech", tags=["speech"])

@router.post("/transcriptions")
async def create_transcription():
    """
    Reserved endpoint for future speech-to-text integration.
    Currently disabled.
    """
    if not settings.GATEWAY_ENABLE_SPEECH_INPUT:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Speech input is currently disabled."
        )
    
    # Future implementation would go here
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Speech transcription is not yet implemented."
    )
