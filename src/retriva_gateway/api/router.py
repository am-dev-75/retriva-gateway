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
from retriva_gateway.api.v2 import health, capabilities, chat, kbs, documents, ingestion, artifacts, speech, metadata, system

# Legacy/internal router
api_router = APIRouter(prefix="/gateway")
api_router.include_router(health.router)
api_router.include_router(capabilities.router)
api_router.include_router(chat.router)
api_router.include_router(kbs.router)
api_router.include_router(documents.router)
api_router.include_router(ingestion.router)
api_router.include_router(artifacts.router)
api_router.include_router(speech.router)
api_router.include_router(metadata.router)
api_router.include_router(system.router)

# Public v2 router (matches Core structure)
api_v2_router = APIRouter(prefix="/api/v2")
api_v2_router.include_router(documents.router)
api_v2_router.include_router(metadata.router)
api_v2_router.include_router(ingestion.router)
api_v2_router.include_router(artifacts.router)
api_v2_router.include_router(capabilities.router)
