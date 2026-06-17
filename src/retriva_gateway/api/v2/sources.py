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

"""Public Gateway API for Connected Sources (dynamic ingestion).

Endpoints:
    POST   /sources                          Create a connected source
    GET    /sources                          List sources
    GET    /sources/{source_id}              Get source details
    PATCH  /sources/{source_id}              Update source
    DELETE /sources/{source_id}              Delete source
    POST   /sources/{source_id}/sync         Trigger manual sync
    POST   /sources/{source_id}/pause        Pause source
    POST   /sources/{source_id}/resume       Resume source
    GET    /sources/{source_id}/status        Get source status
    GET    /sources/{source_id}/runs          List sync runs
    GET    /sources/{source_id}/runs/{run_id} Get single run
    GET    /sources/{source_id}/items         List synced items
"""

from fastapi import APIRouter, HTTPException, Query, status
from typing import List, Optional
from loguru import logger

from retriva_gateway.config import settings
from retriva_gateway.core.source_models import (
    ConnectorType,
    SourceStatus,
    SyncMode,
    SourceInstance,
    SourceRun,
    RunPhase,
    CreateSourceRequest,
    UpdateSourceRequest,
    SourceResponse,
    SourceRunResponse,
    SourceStatusResponse,
    SourceItemState,
    _now,
)
from retriva_gateway.core.json_source_repository import (
    source_repo,
    run_repo,
    checkpoint_repo,
    item_state_repo,
)
from retriva_gateway.core.connector_manager import (
    connector_registry,
    connector_manager,
)

router = APIRouter(prefix="/sources", tags=["sources"])

# States from which a source can be paused
_PAUSABLE_STATES = {
    SourceStatus.ACTIVE,
    SourceStatus.BASELINE_PENDING,
    SourceStatus.BASELINE_RUNNING,
    SourceStatus.CATCHUP_RUNNING,
    SourceStatus.DEGRADED,
}


def _require_dynamic_ingestion() -> None:
    if not settings.DYNAMIC_INGESTION_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dynamic ingestion is not enabled on this Gateway instance.",
        )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(request: CreateSourceRequest):
    """Create a new connected source."""
    _require_dynamic_ingestion()

    # Idempotency: if the client provides an idempotency key and a source
    # with that key already exists, return the existing source.
    if request.idempotency_key:
        existing = await source_repo.get_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            return SourceResponse.from_source(existing)

    # Validate connector type against allowlist
    if not connector_registry.is_allowed(request.connector_type):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported connector type: {request.connector_type}. "
                   f"Allowed: {settings.ALLOWED_CONNECTOR_TYPES}",
        )

    # Parse and validate connector-specific config
    try:
        ct = ConnectorType(request.connector_type)
        descriptor = connector_registry.get(ct)
        validated_config = descriptor.validate_config(request.config)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid source configuration: {e}",
        )

    source = SourceInstance(
        tenant_id=settings.DEFAULT_TENANT_ID,
        connector_type=ct,
        display_name=request.display_name,
        target_kb_id=request.target_kb_id,
        status=SourceStatus.BASELINE_PENDING,
        sync_mode=SyncMode.BASELINE,
        schedule=request.schedule or descriptor.default_schedule(),
        config=validated_config,
        secret_ref=request.secret_ref,
        metadata=request.metadata,
        idempotency_key=request.idempotency_key,
    )

    created = await source_repo.create(source)

    logger.info(
        "Source created: source_id={} connector={} kb={}",
        created.source_id,
        created.connector_type.value,
        created.target_kb_id,
    )

    return SourceResponse.from_source(created)


@router.get("", response_model=List[SourceResponse])
async def list_sources(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List all connected sources for the current tenant."""
    _require_dynamic_ingestion()

    sources = await source_repo.list(settings.DEFAULT_TENANT_ID)
    return [SourceResponse.from_source(s) for s in sources[offset:offset + limit]]


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(source_id: str):
    """Get a connected source by ID."""
    _require_dynamic_ingestion()

    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return SourceResponse.from_source(source)


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source(source_id: str, request: UpdateSourceRequest):
    """Update a connected source."""
    _require_dynamic_ingestion()

    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    updates: dict = {}
    if request.display_name is not None:
        updates["display_name"] = request.display_name
    if request.schedule is not None:
        updates["schedule"] = request.schedule
    if request.metadata is not None:
        updates["metadata"] = request.metadata
    if request.config is not None:
        # Re-validate config through the connector descriptor
        try:
            descriptor = connector_registry.get(source.connector_type)
            updates["config"] = descriptor.validate_config(request.config)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid source configuration: {e}",
            )

    if not updates:
        return SourceResponse.from_source(source)

    updated = await source_repo.update(source_id, updates)
    return SourceResponse.from_source(updated)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: str):
    """Delete a connected source (soft-delete lifecycle)."""
    _require_dynamic_ingestion()

    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    await source_repo.update(source_id, {"status": SourceStatus.DELETING.value})
    await source_repo.update(source_id, {"status": SourceStatus.DELETED.value})

    logger.info("Source deleted: source_id={}", source_id)


# ---------------------------------------------------------------------------
# Lifecycle actions
# ---------------------------------------------------------------------------

@router.post("/{source_id}/sync", response_model=SourceRunResponse)
async def trigger_sync(source_id: str):
    """Trigger a manual sync run for a connected source."""
    _require_dynamic_ingestion()

    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    if source.status in {SourceStatus.DELETED, SourceStatus.DELETING}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot sync a source in {source.status.value} state.",
        )

    # Determine run phase based on current sync mode
    phase_map = {
        SyncMode.BASELINE: RunPhase.BASELINE_SCAN,
        SyncMode.CATCHUP: RunPhase.CATCHUP,
        SyncMode.INCREMENTAL: RunPhase.INCREMENTAL,
    }
    phase = phase_map.get(source.sync_mode, RunPhase.BASELINE_SCAN)

    run = SourceRun(
        source_id=source_id,
        tenant_id=source.tenant_id,
        phase=phase,
    )

    dispatched = await connector_manager.dispatch(source, run)
    return SourceRunResponse.from_run(dispatched)


@router.post("/{source_id}/pause", response_model=SourceResponse)
async def pause_source(source_id: str):
    """Pause a connected source."""
    _require_dynamic_ingestion()

    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    if source.status not in _PAUSABLE_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot pause a source in {source.status.value} state.",
        )

    updated = await source_repo.update(source_id, {
        "status_before_pause": source.status.value,
        "status": SourceStatus.PAUSED.value,
    })
    return SourceResponse.from_source(updated)


@router.post("/{source_id}/resume", response_model=SourceResponse)
async def resume_source(source_id: str):
    """Resume a paused connected source."""
    _require_dynamic_ingestion()

    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    if source.status != SourceStatus.PAUSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot resume a source in {source.status.value} state.",
        )

    restore_status = source.status_before_pause or SourceStatus.BASELINE_PENDING
    updated = await source_repo.update(source_id, {
        "status": restore_status.value,
        "status_before_pause": None,
    })
    return SourceResponse.from_source(updated)


# ---------------------------------------------------------------------------
# Status and runs
# ---------------------------------------------------------------------------

@router.get("/{source_id}/status", response_model=SourceStatusResponse)
async def get_source_status(source_id: str):
    """Get the current status of a connected source."""
    _require_dynamic_ingestion()

    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    # Get the latest run
    runs = await run_repo.list_by_source(source_id)
    latest_run = None
    if runs:
        runs.sort(key=lambda r: r.started_at, reverse=True)
        latest_run = SourceRunResponse.from_run(runs[0])

    checkpoint = await checkpoint_repo.get(source_id)

    return SourceStatusResponse(
        source_id=source.source_id,
        status=source.status,
        sync_mode=source.sync_mode,
        latest_run=latest_run,
        has_checkpoint=checkpoint is not None,
    )


@router.get("/{source_id}/runs", response_model=List[SourceRunResponse])
async def list_runs(
    source_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List all sync runs for a connected source."""
    _require_dynamic_ingestion()

    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    runs = await run_repo.list_by_source(source_id)
    runs.sort(key=lambda r: r.started_at, reverse=True)
    return [SourceRunResponse.from_run(r) for r in runs[offset:offset + limit]]


@router.get("/{source_id}/runs/{run_id}", response_model=SourceRunResponse)
async def get_run(source_id: str, run_id: str):
    """Get a specific sync run."""
    _require_dynamic_ingestion()

    run = await run_repo.get(run_id)
    if run is None or run.source_id != source_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return SourceRunResponse.from_run(run)


@router.get("/{source_id}/items", response_model=List[SourceItemState])
async def list_items(
    source_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List synced items for a connected source."""
    _require_dynamic_ingestion()

    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    items = await item_state_repo.list_by_source(source_id)
    return items[offset:offset + limit]
