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

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, List
from enum import Enum
from datetime import datetime, timezone
import uuid


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SourceStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATING_CONNECTION = "VALIDATING_CONNECTION"
    BASELINE_PENDING = "BASELINE_PENDING"
    BASELINE_RUNNING = "BASELINE_RUNNING"
    CATCHUP_RUNNING = "CATCHUP_RUNNING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    DELETING = "DELETING"
    DELETED = "DELETED"


class SyncMode(str, Enum):
    BASELINE = "baseline"
    CATCHUP = "catchup"
    INCREMENTAL = "incremental"


class ConnectorType(str, Enum):
    MEDIAWIKI = "mediawiki"


class RunPhase(str, Enum):
    BASELINE_SCAN = "baseline_scan"
    CATCHUP = "catchup"
    INCREMENTAL = "incremental"
    VALIDATION = "validation"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ItemStatus(str, Enum):
    PENDING = "pending"
    INDEXED = "indexed"
    DELETED = "deleted"
    ERROR = "error"


class DeletePolicy(str, Enum):
    SOFT_DELETE = "soft_delete"
    HARD_DELETE = "hard_delete"


class AuthMode(str, Enum):
    BOT_PASSWORD = "bot_password"
    OAUTH = "oauth"
    NONE = "none"


class AvailabilityPolicy(str, Enum):
    HIDE_UNTIL_INITIAL_SYNC_COMPLETE = "hide_until_initial_sync_complete"
    SHOW_IMMEDIATELY = "show_immediately"


# ---------------------------------------------------------------------------
# Connector-specific config schemas
# ---------------------------------------------------------------------------

class MediaWikiSourceConfig(BaseModel):
    """Configuration schema for a MediaWiki connected source."""

    api_url: str
    auth_mode: AuthMode = AuthMode.NONE
    allowed_namespaces: List[int] = Field(default_factory=lambda: [0])
    include_categories: List[str] = Field(default_factory=list)
    exclude_categories: List[str] = Field(default_factory=list)
    page_title_prefix: Optional[str] = None
    sync_interval_minutes: int = Field(default=15, ge=1, le=1440)
    delete_policy: DeletePolicy = DeletePolicy.SOFT_DELETE
    availability_policy: AvailabilityPolicy = AvailabilityPolicy.HIDE_UNTIL_INITIAL_SYNC_COMPLETE

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("api_url must not be empty")
        if not v.startswith(("http://", "https://")):
            raise ValueError("api_url must start with http:// or https://")
        return v


# ---------------------------------------------------------------------------
# Domain entities
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_source_id() -> str:
    return f"src_{uuid.uuid4().hex[:12]}"


def _generate_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


class SourceInstance(BaseModel):
    """Core domain entity for a connected source."""

    source_id: str = Field(default_factory=_generate_source_id)
    tenant_id: str = "internal-company"
    connector_type: ConnectorType
    display_name: str
    target_kb_id: str
    status: SourceStatus = SourceStatus.BASELINE_PENDING
    sync_mode: SyncMode = SyncMode.BASELINE
    schedule: Optional[str] = None  # cron expression
    config: Dict[str, Any] = Field(default_factory=dict)
    secret_ref: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    # Stores the status before PAUSED, so resume can restore it
    status_before_pause: Optional[SourceStatus] = None


class SourceCheckpoint(BaseModel):
    """Tracks sync progress for crash recovery and incremental syncs."""

    source_id: str
    checkpoint_type: str = ""  # e.g. "mediawiki_recentchanges"
    baseline_started_at: Optional[str] = None
    last_seen_timestamp: Optional[str] = None
    last_seen_rcid: Optional[int] = None
    cursor: Dict[str, Any] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=_now)


class SourceRun(BaseModel):
    """Individual sync run record."""

    run_id: str = Field(default_factory=_generate_run_id)
    source_id: str
    tenant_id: str = "internal-company"
    phase: RunPhase = RunPhase.BASELINE_SCAN
    status: RunStatus = RunStatus.PENDING
    started_at: str = Field(default_factory=_now)
    finished_at: Optional[str] = None
    processed_items: int = 0
    failed_items: int = 0
    skipped_items: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    last_heartbeat_at: Optional[str] = None


class SourceItemState(BaseModel):
    """Per-item sync mapping between source and Retriva documents."""

    source_id: str
    source_item_id: str  # e.g. "mediawiki:rdwiki:page:12345"
    source_revision: Optional[str] = None
    retriva_doc_id: Optional[str] = None
    content_hash: Optional[str] = None
    status: ItemStatus = ItemStatus.PENDING
    last_synced_at: str = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# API request schemas
# ---------------------------------------------------------------------------

class CreateSourceRequest(BaseModel):
    """Request body for POST /sources."""

    connector_type: str
    display_name: str
    target_kb_id: str
    config: Dict[str, Any] = Field(default_factory=dict)
    secret_ref: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    schedule: Optional[str] = None
    idempotency_key: Optional[str] = None


class UpdateSourceRequest(BaseModel):
    """Request body for PATCH /sources/{source_id}."""

    display_name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    schedule: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# API response schemas
# ---------------------------------------------------------------------------

class SourceResponse(BaseModel):
    """API response for a connected source. Redacts secret_ref."""

    source_id: str
    tenant_id: str
    connector_type: str
    display_name: str
    target_kb_id: str
    status: SourceStatus
    sync_mode: SyncMode
    schedule: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    has_secret: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    last_sync_at: Optional[str] = None
    indexed_item_count: int = 0
    failed_item_count: int = 0

    @classmethod
    def from_source(cls, source: SourceInstance) -> "SourceResponse":
        return cls(
            source_id=source.source_id,
            tenant_id=source.tenant_id,
            connector_type=source.connector_type.value,
            display_name=source.display_name,
            target_kb_id=source.target_kb_id,
            status=source.status,
            sync_mode=source.sync_mode,
            schedule=source.schedule,
            config=source.config,
            has_secret=bool(source.secret_ref),
            metadata=source.metadata,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )


class SourceRunResponse(BaseModel):
    """API response for a sync run."""

    run_id: str
    source_id: str
    phase: RunPhase
    status: RunStatus
    started_at: str
    finished_at: Optional[str] = None
    processed_items: int = 0
    failed_items: int = 0
    skipped_items: int = 0
    error_code: Optional[str] = None

    @classmethod
    def from_run(cls, run: SourceRun) -> "SourceRunResponse":
        return cls(
            run_id=run.run_id,
            source_id=run.source_id,
            phase=run.phase,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            processed_items=run.processed_items,
            failed_items=run.failed_items,
            skipped_items=run.skipped_items,
            error_code=run.error_code,
        )


class SourceStatusResponse(BaseModel):
    """API response for GET /sources/{source_id}/status."""

    source_id: str
    status: SourceStatus
    sync_mode: SyncMode
    latest_run: Optional[SourceRunResponse] = None
    has_checkpoint: bool = False


class SourceCheckpointResponse(BaseModel):
    """API response for a source checkpoint."""

    source_id: str
    checkpoint_type: str
    baseline_started_at: Optional[str] = None
    last_seen_timestamp: Optional[str] = None
    last_seen_rcid: Optional[int] = None
    cursor: Dict[str, Any] = Field(default_factory=dict)
    updated_at: str

    @classmethod
    def from_checkpoint(cls, cp: SourceCheckpoint) -> "SourceCheckpointResponse":
        return cls(
            source_id=cp.source_id,
            checkpoint_type=cp.checkpoint_type,
            baseline_started_at=cp.baseline_started_at,
            last_seen_timestamp=cp.last_seen_timestamp,
            last_seen_rcid=cp.last_seen_rcid,
            cursor=cp.cursor,
            updated_at=cp.updated_at,
        )
