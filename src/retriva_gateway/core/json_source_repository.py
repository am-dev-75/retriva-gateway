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

"""JSON file-backed implementations of the source repository interfaces.

Data is stored in ``{DYNAMIC_INGESTION_DATA_DIR}/`` with one JSON file per
entity type.  Thread-safety is achieved via ``asyncio.Lock`` (sufficient for
the single-process Gateway).
"""

import asyncio
import json
from pathlib import Path
from typing import Optional, List
from loguru import logger

from retriva_gateway.config import settings
from retriva_gateway.core.source_models import (
    SourceInstance,
    SourceRun,
    SourceCheckpoint,
    SourceItemState,
    _now,
)
from retriva_gateway.core.source_repository import (
    SourceRepository,
    SourceRunRepository,
    SourceCheckpointRepository,
    SourceItemStateRepository,
)


def _data_dir() -> Path:
    p = Path(settings.DYNAMIC_INGESTION_DATA_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

class JsonSourceRepository(SourceRepository):
    """Persist SourceInstance entities in a JSON file."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @property
    def _path(self) -> Path:
        return _data_dir() / "sources.json"

    async def create(self, source: SourceInstance) -> SourceInstance:
        async with self._lock:
            data = _load_json(self._path)
            data[source.source_id] = source.model_dump()
            _save_json(self._path, data)
        return source

    async def get(self, source_id: str) -> Optional[SourceInstance]:
        data = _load_json(self._path)
        raw = data.get(source_id)
        if raw is None:
            return None
        return SourceInstance(**raw)

    async def list(self, tenant_id: str) -> List[SourceInstance]:
        data = _load_json(self._path)
        return [
            SourceInstance(**v)
            for v in data.values()
            if v.get("tenant_id") == tenant_id
        ]

    async def update(self, source_id: str, updates: dict) -> SourceInstance:
        async with self._lock:
            data = _load_json(self._path)
            raw = data.get(source_id)
            if raw is None:
                raise KeyError(f"Source {source_id} not found")
            raw.update(updates)
            raw["updated_at"] = _now()
            data[source_id] = raw
            _save_json(self._path, data)
            return SourceInstance(**raw)

    async def delete(self, source_id: str) -> None:
        async with self._lock:
            data = _load_json(self._path)
            data.pop(source_id, None)
            _save_json(self._path, data)

    async def get_by_idempotency_key(self, key: str) -> Optional[SourceInstance]:
        data = _load_json(self._path)
        for v in data.values():
            if v.get("idempotency_key") == key:
                return SourceInstance(**v)
        return None


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

class JsonSourceRunRepository(SourceRunRepository):
    """Persist SourceRun entities in a JSON file."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @property
    def _path(self) -> Path:
        return _data_dir() / "runs.json"

    async def create(self, run: SourceRun) -> SourceRun:
        async with self._lock:
            data = _load_json(self._path)
            data[run.run_id] = run.model_dump()
            _save_json(self._path, data)
        return run

    async def get(self, run_id: str) -> Optional[SourceRun]:
        data = _load_json(self._path)
        raw = data.get(run_id)
        if raw is None:
            return None
        return SourceRun(**raw)

    async def list_by_source(self, source_id: str) -> List[SourceRun]:
        data = _load_json(self._path)
        return [
            SourceRun(**v)
            for v in data.values()
            if v.get("source_id") == source_id
        ]

    async def update(self, run_id: str, updates: dict) -> SourceRun:
        async with self._lock:
            data = _load_json(self._path)
            raw = data.get(run_id)
            if raw is None:
                raise KeyError(f"Run {run_id} not found")
            raw.update(updates)
            data[run_id] = raw
            _save_json(self._path, data)
            return SourceRun(**raw)


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------

class JsonSourceCheckpointRepository(SourceCheckpointRepository):
    """Persist SourceCheckpoint entities in a JSON file."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @property
    def _path(self) -> Path:
        return _data_dir() / "checkpoints.json"

    async def get(self, source_id: str) -> Optional[SourceCheckpoint]:
        data = _load_json(self._path)
        raw = data.get(source_id)
        if raw is None:
            return None
        return SourceCheckpoint(**raw)

    async def save(self, checkpoint: SourceCheckpoint) -> SourceCheckpoint:
        async with self._lock:
            data = _load_json(self._path)
            checkpoint.updated_at = _now()
            data[checkpoint.source_id] = checkpoint.model_dump()
            _save_json(self._path, data)
        return checkpoint


# ---------------------------------------------------------------------------
# Item states
# ---------------------------------------------------------------------------

class JsonSourceItemStateRepository(SourceItemStateRepository):
    """Persist SourceItemState entities in a JSON file."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @property
    def _path(self) -> Path:
        return _data_dir() / "item_states.json"

    def _key(self, source_id: str, source_item_id: str) -> str:
        return f"{source_id}::{source_item_id}"

    async def upsert(self, item: SourceItemState) -> SourceItemState:
        async with self._lock:
            data = _load_json(self._path)
            key = self._key(item.source_id, item.source_item_id)
            data[key] = item.model_dump()
            _save_json(self._path, data)
        return item

    async def get(self, source_id: str, source_item_id: str) -> Optional[SourceItemState]:
        data = _load_json(self._path)
        key = self._key(source_id, source_item_id)
        raw = data.get(key)
        if raw is None:
            return None
        return SourceItemState(**raw)

    async def list_by_source(self, source_id: str) -> List[SourceItemState]:
        data = _load_json(self._path)
        return [
            SourceItemState(**v)
            for v in data.values()
            if v.get("source_id") == source_id
        ]


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

source_repo = JsonSourceRepository()
run_repo = JsonSourceRunRepository()
checkpoint_repo = JsonSourceCheckpointRepository()
item_state_repo = JsonSourceItemStateRepository()
