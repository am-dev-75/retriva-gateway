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

"""Connector manager, registry, and connector descriptors.

The ConnectorRegistry holds a mapping of ConnectorType → ConnectorDescriptor.
Each descriptor knows how to validate a source config and provides a default
sync schedule.

The ConnectorManager accepts sync requests from the API layer and dispatches
work to connector workers.  In Milestone 1, dispatch is a no-op that logs the
intent — actual worker processes are out of scope.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

from loguru import logger

from retriva_gateway.config import settings
from retriva_gateway.core.source_models import (
    ConnectorType,
    MediaWikiSourceConfig,
    SourceInstance,
    SourceRun,
    RunStatus,
    _now,
)
from retriva_gateway.core.json_source_repository import run_repo


# ---------------------------------------------------------------------------
# Connector descriptor protocol
# ---------------------------------------------------------------------------

class ConnectorDescriptor(ABC):
    """Describes a connector type and validates its configuration."""

    @property
    @abstractmethod
    def connector_type(self) -> ConnectorType:
        ...

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize connector-specific config.

        Returns the validated config dict.
        Raises ValueError on invalid config.
        """
        ...

    def default_schedule(self) -> str:
        """Return the default cron schedule for this connector type."""
        return "*/15 * * * *"


# ---------------------------------------------------------------------------
# MediaWiki descriptor
# ---------------------------------------------------------------------------

class MediaWikiConnectorDescriptor(ConnectorDescriptor):
    """Descriptor for MediaWiki connected sources."""

    @property
    def connector_type(self) -> ConnectorType:
        return ConnectorType.MEDIAWIKI

    def validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Parse config through the MediaWikiSourceConfig pydantic model."""
        validated = MediaWikiSourceConfig(**config)
        return validated.model_dump()

    def default_schedule(self) -> str:
        return "*/15 * * * *"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ConnectorRegistry:
    """Maps ConnectorType to its descriptor."""

    def __init__(self) -> None:
        self._descriptors: Dict[ConnectorType, ConnectorDescriptor] = {}

    def register(self, descriptor: ConnectorDescriptor) -> None:
        self._descriptors[descriptor.connector_type] = descriptor

    def get(self, connector_type: ConnectorType) -> ConnectorDescriptor:
        desc = self._descriptors.get(connector_type)
        if desc is None:
            raise ValueError(f"Unsupported connector type: {connector_type}")
        return desc

    def is_allowed(self, connector_type_str: str) -> bool:
        return connector_type_str in settings.ALLOWED_CONNECTOR_TYPES


# Build the default registry with all known descriptors.
connector_registry = ConnectorRegistry()
connector_registry.register(MediaWikiConnectorDescriptor())


# ---------------------------------------------------------------------------
# Connector Manager
# ---------------------------------------------------------------------------

class ConnectorManager:
    """Orchestrates sync run dispatch.

    In Milestone 1, ``dispatch`` only creates the SourceRun record and logs
    the intent.  Actual worker launch is out of scope.
    """

    def __init__(self, registry: ConnectorRegistry) -> None:
        self._registry = registry

    async def dispatch(self, source: SourceInstance, run: SourceRun) -> SourceRun:
        """Create a run record and (M1: log the dispatch intent)."""
        run.status = RunStatus.PENDING
        created_run = await run_repo.create(run)

        logger.info(
            "Sync run dispatched: source_id={} run_id={} connector={}",
            source.source_id,
            run.run_id,
            source.connector_type.value,
        )

        return created_run


connector_manager = ConnectorManager(connector_registry)
