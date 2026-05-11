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
from retriva_gateway.core.client import core_client

router = APIRouter(prefix="/metadata", tags=["metadata"])

@router.get("/schema")
async def get_metadata_schema():
    """Proxy Core metadata schema endpoint."""
    return await core_client.get_metadata_schema()

@router.get("/{field}/values")
async def get_metadata_values(field: str):
    """Proxy Core metadata field values endpoint."""
    return await core_client.get_metadata_values(field)
