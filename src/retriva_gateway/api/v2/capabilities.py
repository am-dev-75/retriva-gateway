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

from fastapi import APIRouter
from retriva_gateway.core.models import CapabilitiesResponse
from retriva_gateway.config import settings

router = APIRouter(tags=["capabilities"])

@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities():
    return CapabilitiesResponse(
        chat=True,
        knowledge_bases=True,
        documents=True,
        ingestion=True,
        artifacts=settings.GATEWAY_ENABLE_ARTIFACTS,
        folder_upload=settings.GATEWAY_ENABLE_FOLDER_UPLOAD,
        speech_input=settings.GATEWAY_ENABLE_SPEECH_INPUT,
        auth=settings.GATEWAY_ENABLE_AUTH
    )
