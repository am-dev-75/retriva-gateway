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

"""Internal worker API for dynamic ingestion connectors.

These endpoints are called by connector workers, not by the WebUI.
When ``GATEWAY_INTERNAL_SERVICE_TOKEN`` is configured, requests must include
the ``X-Service-Token`` header.

Endpoints:
    POST /internal/sources/{source_id}/runs/{run_id}/heartbeat
    POST /internal/sources/{source_id}/runs/{run_id}/events
    POST /internal/sources/{source_id}/runs/{run_id}/complete
    POST /internal/sources/{source_id}/ingestion-session
"""

from fastapi import APIRouter, HTTPException, Header, status
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from loguru import logger

from retriva_gateway.config import settings
from retriva_gateway.core.source_models import (
    SourceStatus,
    SyncMode,
    RunStatus,
    ItemStatus,
    SourceCheckpoint,
    SourceItemState,
    SourceCheckpointResponse,
    _now,
)
from retriva_gateway.core.json_source_repository import (
    source_repo,
    run_repo,
    checkpoint_repo,
    item_state_repo,
)

router = APIRouter(prefix="/internal/sources", tags=["internal"])


# ---------------------------------------------------------------------------
# Service authentication
# ---------------------------------------------------------------------------

async def _verify_service_token(x_service_token: Optional[str] = Header(None)) -> None:
    """Verify service token if configured."""
    if settings.GATEWAY_INTERNAL_SERVICE_TOKEN and x_service_token != settings.GATEWAY_INTERNAL_SERVICE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing service token.",
        )


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class HeartbeatRequest(BaseModel):
    processed_items: Optional[int] = None
    failed_items: Optional[int] = None
    skipped_items: Optional[int] = None


class ItemEvent(BaseModel):
    source_item_id: str
    source_revision: Optional[str] = None
    retriva_doc_id: Optional[str] = None
    content_hash: Optional[str] = None
    status: ItemStatus = ItemStatus.INDEXED


class EventsRequest(BaseModel):
    events: List[ItemEvent]


class CompleteRequest(BaseModel):
    status: str  # "completed" or "failed"
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    checkpoint: Optional[Dict[str, Any]] = None
    processed_items: Optional[int] = None
    failed_items: Optional[int] = None
    skipped_items: Optional[int] = None


class IngestionSessionRequest(BaseModel):
    run_id: Optional[str] = None


class IngestionSessionResponse(BaseModel):
    kb_id: str
    tenant_id: str
    source_id: str
    run_id: Optional[str] = None
    batch_metadata: Dict[str, Any]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/{source_id}/runs/{run_id}/heartbeat")
async def heartbeat(
    source_id: str,
    run_id: str,
    request: HeartbeatRequest,
    x_service_token: Optional[str] = Header(None),
):
    """Worker liveness ping. Updates run counters."""
    await _verify_service_token(x_service_token)

    run = await run_repo.get(run_id)
    if run is None or run.source_id != source_id:
        raise HTTPException(status_code=404, detail="Run not found")

    updates: dict = {"last_heartbeat_at": _now()}
    if request.processed_items is not None:
        updates["processed_items"] = request.processed_items
    if request.failed_items is not None:
        updates["failed_items"] = request.failed_items
    if request.skipped_items is not None:
        updates["skipped_items"] = request.skipped_items

    await run_repo.update(run_id, updates)
    return {"status": "ok"}


@router.post("/{source_id}/runs/{run_id}/events")
async def run_events(
    source_id: str,
    run_id: str,
    request: EventsRequest,
    x_service_token: Optional[str] = Header(None),
):
    """Batch of item state updates from a worker."""
    await _verify_service_token(x_service_token)

    run = await run_repo.get(run_id)
    if run is None or run.source_id != source_id:
        raise HTTPException(status_code=404, detail="Run not found")

    for event in request.events:
        item = SourceItemState(
            source_id=source_id,
            source_item_id=event.source_item_id,
            source_revision=event.source_revision,
            retriva_doc_id=event.retriva_doc_id,
            content_hash=event.content_hash,
            status=event.status,
        )
        await item_state_repo.upsert(item)

    logger.debug(
        "Processed {} item events: source_id={} run_id={}",
        len(request.events),
        source_id,
        run_id,
    )

    return {"processed": len(request.events)}


@router.post("/{source_id}/runs/{run_id}/complete")
async def complete_run(
    source_id: str,
    run_id: str,
    request: CompleteRequest,
    x_service_token: Optional[str] = Header(None),
):
    """Mark a run as completed or failed. Optionally save checkpoint."""
    await _verify_service_token(x_service_token)

    run = await run_repo.get(run_id)
    if run is None or run.source_id != source_id:
        raise HTTPException(status_code=404, detail="Run not found")

    # Update run
    run_updates: dict = {
        "status": request.status,
        "finished_at": _now(),
    }
    if request.error_code:
        run_updates["error_code"] = request.error_code
    if request.error_message:
        run_updates["error_message"] = request.error_message
    if request.processed_items is not None:
        run_updates["processed_items"] = request.processed_items
    if request.failed_items is not None:
        run_updates["failed_items"] = request.failed_items
    if request.skipped_items is not None:
        run_updates["skipped_items"] = request.skipped_items

    await run_repo.update(run_id, run_updates)

    # Save checkpoint if provided
    if request.checkpoint and request.status == RunStatus.COMPLETED.value:
        cp = SourceCheckpoint(
            source_id=source_id,
            **request.checkpoint,
        )
        await checkpoint_repo.save(cp)

    # Update source status based on completion
    source = await source_repo.get(source_id)
    if source and request.status == RunStatus.COMPLETED.value:
        # First-sync lifecycle: baseline → catchup → active
        if source.sync_mode == SyncMode.BASELINE:
            await source_repo.update(source_id, {
                "sync_mode": SyncMode.CATCHUP.value,
                "status": SourceStatus.CATCHUP_RUNNING.value,
            })
        elif source.sync_mode == SyncMode.CATCHUP:
            await source_repo.update(source_id, {
                "sync_mode": SyncMode.INCREMENTAL.value,
                "status": SourceStatus.ACTIVE.value,
            })
    elif source and request.status == RunStatus.FAILED.value:
        await source_repo.update(source_id, {
            "status": SourceStatus.FAILED.value,
        })

    logger.info(
        "Run completed: run_id={} source_id={} status={}",
        run_id,
        source_id,
        request.status,
    )

    return {"status": "ok"}


@router.post("/{source_id}/ingestion-session", response_model=IngestionSessionResponse)
async def create_ingestion_session(
    source_id: str,
    request: Optional[IngestionSessionRequest] = None,
    x_service_token: Optional[str] = Header(None),
):
    """Issue a scoped ingestion context for a connector worker.

    In M1 this returns the KB ID and metadata needed for the worker to
    construct ingestion requests.  A real implementation would issue a
    short-lived, scoped token.

    Optionally accepts a ``run_id`` to scope the session to a specific run.
    """
    await _verify_service_token(x_service_token)

    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    run_id = request.run_id if request else None
    batch_metadata: Dict[str, Any] = {
        "source_type": source.connector_type.value,
        "source_id": source.source_id,
    }
    if run_id:
        batch_metadata["run_id"] = run_id

    return IngestionSessionResponse(
        kb_id=source.target_kb_id,
        tenant_id=source.tenant_id,
        source_id=source.source_id,
        run_id=run_id,
        batch_metadata=batch_metadata,
    )


@router.get("/{source_id}/checkpoint", response_model=SourceCheckpointResponse)
async def get_checkpoint(
    source_id: str,
    x_service_token: Optional[str] = Header(None),
):
    """Return the latest authoritative checkpoint for the given connected source."""
    await _verify_service_token(x_service_token)

    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    cp = await checkpoint_repo.get(source_id)
    if cp is None:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    return SourceCheckpointResponse.from_checkpoint(cp)
