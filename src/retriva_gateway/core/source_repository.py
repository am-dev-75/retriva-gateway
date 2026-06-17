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

from abc import ABC, abstractmethod
from typing import Optional, List
from retriva_gateway.core.source_models import (
    SourceInstance,
    SourceRun,
    SourceCheckpoint,
    SourceItemState,
)


class SourceRepository(ABC):
    """Abstract repository for SourceInstance persistence."""

    @abstractmethod
    async def create(self, source: SourceInstance) -> SourceInstance:
        ...

    @abstractmethod
    async def get(self, source_id: str) -> Optional[SourceInstance]:
        ...

    @abstractmethod
    async def list(self, tenant_id: str) -> List[SourceInstance]:
        ...

    @abstractmethod
    async def update(self, source_id: str, updates: dict) -> SourceInstance:
        ...

    @abstractmethod
    async def delete(self, source_id: str) -> None:
        ...

    @abstractmethod
    async def get_by_idempotency_key(self, key: str) -> Optional[SourceInstance]:
        ...


class SourceRunRepository(ABC):
    """Abstract repository for SourceRun persistence."""

    @abstractmethod
    async def create(self, run: SourceRun) -> SourceRun:
        ...

    @abstractmethod
    async def get(self, run_id: str) -> Optional[SourceRun]:
        ...

    @abstractmethod
    async def list_by_source(self, source_id: str) -> List[SourceRun]:
        ...

    @abstractmethod
    async def update(self, run_id: str, updates: dict) -> SourceRun:
        ...


class SourceCheckpointRepository(ABC):
    """Abstract repository for SourceCheckpoint persistence."""

    @abstractmethod
    async def get(self, source_id: str) -> Optional[SourceCheckpoint]:
        ...

    @abstractmethod
    async def save(self, checkpoint: SourceCheckpoint) -> SourceCheckpoint:
        ...


class SourceItemStateRepository(ABC):
    """Abstract repository for SourceItemState persistence."""

    @abstractmethod
    async def upsert(self, item: SourceItemState) -> SourceItemState:
        ...

    @abstractmethod
    async def get(self, source_id: str, source_item_id: str) -> Optional[SourceItemState]:
        ...

    @abstractmethod
    async def list_by_source(self, source_id: str) -> List[SourceItemState]:
        ...
