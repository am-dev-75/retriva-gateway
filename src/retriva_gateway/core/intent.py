# Copyright (C) 2026 Andrea Marson (am.dev.75@gmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Granular chat-intent detection (deterministic, no provider calls).

Two consumers:

1. **RAG routing** — ``CATALOG_DOCUMENT_LIST`` /
   ``CATALOG_DOCUMENT_COUNT`` / ``METADATA_FILTERED_RAG`` requests are
   answered by the catalog/metadata-filter paths instead of plain RAG
   (``PURE_RAG``).
2. **Agent-mode routing** — ``CRM_WORKFLOW`` messages (company
   intelligence workflows: ACP cohorts, qualification, imports,
   campaigns) must run the bounded tool-calling agent loop even when
   the client did not explicitly opt in; answering them from the
   knowledge-base pipeline produces the generic grounding refusal.

Detection is regex-based and synchronous in cost: the only await is the
(optional) dynamic metadata-schema lookup for ``key=value`` filters.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from retriva_gateway.core.client import core_client


class Intent(Enum):
    """Detected chat intent (routing only — never authorization)."""

    PURE_RAG = "pure_rag"
    CATALOG_DOCUMENT_LIST = "catalog_document_list"
    CATALOG_DOCUMENT_COUNT = "catalog_document_count"
    METADATA_FILTERED_RAG = "metadata_filtered_rag"
    CRM_WORKFLOW = "crm_workflow"


# Explicit metadata-filter syntax: @project:apollo, department:r&d.
_EXPLICIT_FILTER = re.compile(
    r"(?:^|\s)@?(?P<key>[a-zA-Z_][a-zA-Z0-9_\-]*)"
    r":(?P<value>[^\s:@]+)")
# Dynamic schema syntax: project=apollo (validated against the
# ingestion metadata schema before it counts as a filter).
_DYNAMIC_FILTER = re.compile(
    r"(?:^|\s)(?P<key>[a-zA-Z_][a-zA-Z0-9_\-]*)="
    r"(?P<value>[^\s=]+)")

_CATALOG_LIST = re.compile(
    r"\b(list|show|enumerate)\b.*\b(documents?|files?|docs)\b"
    r"|\b(documents?|files?)\b\s+(in|of|inside)\b.{0,40}\b"
    r"(knowledge\s*base|kb)\b",
    re.IGNORECASE)
_CATALOG_COUNT = re.compile(
    r"\bhow many\b.*\b(files?|documents?|docs)\b", re.IGNORECASE)

# CRM workflow intents: narrow verb+noun pairs over the accepted
# company-intelligence workflows.  A match routes the message to the
# bounded agent loop (the tools — not this module — decide what runs;
# authorization stays with the trusted principal).
_CRM_WORKFLOW = re.compile(
    r"\b(extrapolat\w*|propose|create|derive|rebuild|generate|review|"
    r"approve|activat\w*|rollback|roll\s*back)\b[^\n]{0,120}\b"
    r"(ACP|average\s+customer\s+profile|reference\s+cohort|"
    r"cohort)\b"
    r"|\bcohort\b[^\n]{0,120}\b(propose|proposal|approve|approval|"
    r"version)\b"
    r"|\b(qualify|qualification)\b[^\n]{0,80}\b"
    r"(candidates?|workbook|job)\b"
    r"|\b(analyz\w+|commit|reject)\b[^\n]{0,80}\b"
    r"(import|batch|workbook)\b"
    r"|\b(campaign)\b[^\n]{0,80}\b(audience|create|approve|commit|"
    r"outcome|history|addressed)\b"
    r"|\b(import)\b[^\n]{0,80}\b(campaign|company\s+history)\b",
    re.IGNORECASE)


class IntentDetector:
    """Deterministic chat-intent detection (no provider calls)."""

    @staticmethod
    async def _schema_fields() -> Optional[Dict[str, Any]]:
        try:
            schema = await core_client.get_metadata_schema()
        except Exception:  # noqa: BLE001 - schema is advisory only
            return None
        if not isinstance(schema, dict):
            return None
        properties = schema.get("properties")
        return properties if isinstance(properties, dict) else None

    @staticmethod
    async def analyze(message: str) -> Tuple[Intent, Dict[str, str]]:
        """Detect the intent of one chat message.

        Returns ``(intent, meta)`` where ``meta`` carries extracted
        metadata filters (``{key: value}``) for
        ``METADATA_FILTERED_RAG`` and is empty otherwise.
        """
        text = message or ""
        filters: Dict[str, str] = {}
        for match in _EXPLICIT_FILTER.finditer(text):
            value = match.group("value").rstrip(".,;:!?")
            filters[match.group("key")] = value
        if filters:
            return Intent.METADATA_FILTERED_RAG, dict(filters)
        if _CATALOG_LIST.search(text):
            return Intent.CATALOG_DOCUMENT_LIST, {}
        if _CATALOG_COUNT.search(text):
            return Intent.CATALOG_DOCUMENT_COUNT, {}
        dynamic = {m.group("key"): m.group("value")
                   for m in _DYNAMIC_FILTER.finditer(text)}
        if dynamic:
            fields = await IntentDetector._schema_fields()
            if fields is not None:
                known = {key: value for key, value in dynamic.items()
                         if key in fields}
                if known:
                    return Intent.METADATA_FILTERED_RAG, dict(known)
        if _CRM_WORKFLOW.search(text):
            return Intent.CRM_WORKFLOW, {}
        return Intent.PURE_RAG, {}

    @staticmethod
    def is_crm_workflow(message: str) -> bool:
        """Synchronous CRM-workflow check for the chat router."""
        return bool(_CRM_WORKFLOW.search(message or ""))
