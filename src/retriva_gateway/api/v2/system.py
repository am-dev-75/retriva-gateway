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
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from pathlib import Path
from retriva_gateway.core.client import core_client
from retriva_gateway.config import settings
from loguru import logger

router = APIRouter(prefix="/system", tags=["system"])


class JobSummary(BaseModel):
    """Full job status with pipeline stage information, passed through from Core."""
    job_id: str
    status: str
    source: str
    job_type: str
    current_stage: Optional[str] = None
    stages_completed: List[str] = Field(default_factory=list)
    stage_detail: Optional[str] = None
    progress: Optional[int] = None
    created_at: str
    updated_at: str
    error: Optional[str] = None


class SystemStatusResponse(BaseModel):
    jobs: Dict[str, int]
    staged_files: int


class SystemStatusDetailResponse(BaseModel):
    """Aggregated counts plus the full job list for dashboard display."""
    jobs: Dict[str, int]
    staged_files: int
    job_list: List[JobSummary] = Field(default_factory=list)


# Map Core JobStatus values to display categories
_STATUS_MAP = {
    "pending": "enqueued",
    "running": "processing",
    "cancelling": "processing",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "failed",
}


def _aggregate_jobs(jobs: List[Dict[str, Any]]) -> Dict[str, int]:
    job_counts = {"enqueued": 0, "processing": 0, "completed": 0, "failed": 0}
    for job in jobs:
        raw_status = job.get("status", "unknown")
        mapped = _STATUS_MAP.get(raw_status, raw_status)
        if mapped in job_counts:
            job_counts[mapped] += 1
        else:
            job_counts[mapped] = 1
    return job_counts


def _count_staged_files() -> int:
    staged_count = 0
    tmp_dir = Path(settings.GATEWAY_UPLOAD_TMP_DIR)
    if tmp_dir.exists() and tmp_dir.is_dir():
        for path in tmp_dir.rglob('*'):
            if path.is_file():
                staged_count += 1
    return staged_count


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status():
    jobs = []
    try:
        jobs = await core_client.list_jobs()
    except Exception as e:
        logger.error(f"Failed to fetch jobs from Core: {e}")

    return SystemStatusResponse(
        jobs=_aggregate_jobs(jobs),
        staged_files=_count_staged_files(),
    )


@router.get("/status/detail", response_model=SystemStatusDetailResponse)
async def get_system_status_detail():
    """Aggregated counts plus the full job list with stage/progress info."""
    jobs = []
    try:
        jobs = await core_client.list_jobs()
    except Exception as e:
        logger.error(f"Failed to fetch jobs from Core: {e}")

    return SystemStatusDetailResponse(
        jobs=_aggregate_jobs(jobs),
        staged_files=_count_staged_files(),
        job_list=[JobSummary(**j) for j in jobs],
    )


@router.get("/jobs", response_model=List[JobSummary])
async def list_jobs():
    """List all ingestion jobs with full stage/progress detail."""
    try:
        jobs = await core_client.list_jobs()
        return [JobSummary(**j) for j in jobs]
    except Exception as e:
        logger.error(f"Failed to fetch jobs from Core: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/jobs/{job_id}", response_model=JobSummary)
async def get_job(job_id: str):
    """Get detailed status of a specific job."""
    try:
        job = await core_client.get_job(job_id)
        return JobSummary(**job)
    except Exception as e:
        logger.error(f"Failed to fetch job {job_id} from Core: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
