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
import threading
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

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
    r"|\b(enrich\w*|accept)\b[^\n]{0,80}\b"
    r"(customers?|companies?|cohorts?|evidence|members?|results?|"
    r"observations?|job)\b"
    r"|\b(enrich\w*)\b[^\n]{0,24}\b(them|it|those|all)\b"
    r"|\b(analyz\w+|commit|reject)\b[^\n]{0,80}\b"
    r"(import|batch|workbook)\b"
    r"|\b(campaign)\b[^\n]{0,80}\b(audience|create|approve|commit|"
    r"outcome|history|addressed)\b"
    r"|\b(import)\b[^\n]{0,80}\b(campaign|company\s+history)\b",
    re.IGNORECASE)

# Sticky-continuation guard (review fix 17): interrogative how-to /
# what-is framings and generic knowledge phrasing are NEVER routed by
# stickiness, even inside an active workflow — only the workflow regex
# itself routes those.
_KNOWLEDGE_FRAMING = re.compile(
    r"^\s*(how\s+(do|can|to|does|did)|what\s+(is|are|does)|why\s+"
    r"(is|do|does)|when\s+(is|do|does)|explain|tell\s+me\s+about|"
    r"give\s+me\s+an?\s+overview|cos'?è|come\s+(si|funziona)|che\s+cos"
    r"?'?è)\b",
    re.IGNORECASE)


class IntentDetector:
    """Deterministic chat-intent detection (no provider calls)."""

    # Workflow stickiness (Spec 021 review fix 17): the staged
    # ACP/evidence flow spans several turns whose confirmation replies
    # ("yes, enrich them", "accept the results") match no workflow
    # pattern, yet they must keep driving the agent loop — not fall
    # back to the knowledge base.  After a workflow turn, the next
    # message of the SAME session stays in workflow context for a
    # bounded number of turns unless it is clearly a knowledge question
    # (explicit filter/catalog/interrogative framing).  Keyed by
    # session; entries are tiny and self-expiring.
    _WORKFLOW_STICKY_TURNS = 3
    _STICKY: Dict[str, List[int]] = {}
    _STICKY_LOCK = threading.Lock()

    @staticmethod
    def _sticky_key(message_key: Optional[str]) -> Optional[str]:
        return message_key or None

    @staticmethod
    def _hit_sticky(key: Optional[str]) -> bool:
        if not key:
            return False
        with IntentDetector._STICKY_LOCK:
            turns = IntentDetector._STICKY.get(key)
            if not turns:
                return False
            return turns[0] > 0

    @staticmethod
    def _mark_sticky(key: Optional[str]) -> None:
        if not key:
            return
        with IntentDetector._STICKY_LOCK:
            # Bounded registry: drop exhausted entries opportunistically.
            IntentDetector._STICKY = {
                k: v for k, v in IntentDetector._STICKY.items() if v[0] > 0}
            IntentDetector._STICKY[key] = [
                IntentDetector._WORKFLOW_STICKY_TURNS]

    @staticmethod
    def _consume_sticky(key: Optional[str]) -> None:
        if not key:
            return
        with IntentDetector._STICKY_LOCK:
            turns = IntentDetector._STICKY.get(key)
            if turns:
                turns[0] -= 1
                if turns[0] <= 0:
                    IntentDetector._STICKY.pop(key, None)

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
    async def analyze(message: str, *,
                      session_key: Optional[str] = None) \
            -> Tuple[Intent, Dict[str, str]]:
        """Detect the intent of one chat message.

        Returns ``(intent, meta)`` where ``meta`` carries extracted
        metadata filters (``{key: value}``) for
        ``METADATA_FILTERED_RAG`` and is empty otherwise.  When a
        ``session_key`` is given, a workflow turn arms stickiness so the
        flow's short confirmation replies keep routing to the agent
        loop (bounded turns; explicit knowledge questions still win).
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
        workflow = bool(_CRM_WORKFLOW.search(text))
        if not workflow and IntentDetector._hit_sticky(session_key) \
                and not _KNOWLEDGE_FRAMING.search(text):
            # Sticky continuation: a short approval/confirmation turn
            # inside an active workflow keeps the loop.
            IntentDetector._consume_sticky(session_key)
            return Intent.CRM_WORKFLOW, {}
        if workflow:
            IntentDetector._mark_sticky(session_key)
            return Intent.CRM_WORKFLOW, {}
        return Intent.PURE_RAG, {}

    @staticmethod
    def is_crm_workflow(message: str, *,
                        session_key: Optional[str] = None) -> bool:
        """Synchronous CRM-workflow check for the chat router."""
        text = message or ""
        if _CRM_WORKFLOW.search(text):
            return True
        # Sticky continuation mirrors analyze() without the async
        # metadata lookup: explicit filter/catalog/dynamic-filter
        # framings are checked by the router BEFORE this call; a
        # knowledge-framed message is never sticky-routed.
        return (IntentDetector._hit_sticky(session_key)
                and not _KNOWLEDGE_FRAMING.search(text))
