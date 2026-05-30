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
from pydantic import BaseModel
from typing import Dict, Any
from pathlib import Path
from retriva_gateway.core.client import core_client
from retriva_gateway.config import settings
from loguru import logger

router = APIRouter(prefix="/system", tags=["system"])

class SystemStatusResponse(BaseModel):
    jobs: Dict[str, int]
    staged_files: int

@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status():
    jobs = []
    try:
        jobs = await core_client.list_jobs()
    except Exception as e:
        logger.error(f"Failed to fetch jobs from Core: {e}")
        # Proceed with empty jobs to still return staged_files

    # Map Core JobStatus values to display categories
    _STATUS_MAP = {
        "pending": "enqueued",
        "running": "processing",
        "cancelling": "processing",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "failed",
    }

    job_counts = {
        "enqueued": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0
    }

    for job in jobs:
        raw_status = job.get("status", "unknown")
        mapped = _STATUS_MAP.get(raw_status, raw_status)
        if mapped in job_counts:
            job_counts[mapped] += 1
        else:
            job_counts[mapped] = 1

    staged_count = 0
    tmp_dir = Path(settings.GATEWAY_UPLOAD_TMP_DIR)
    if tmp_dir.exists() and tmp_dir.is_dir():
        for path in tmp_dir.rglob('*'):
            if path.is_file():
                staged_count += 1

    return SystemStatusResponse(
        jobs=job_counts,
        staged_files=staged_count
    )
