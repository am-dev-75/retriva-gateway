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

import re
import time
from loguru import logger
from retriva_gateway.core.client import core_client

class Intent:
    CATALOG_DOCUMENT_LIST = "catalog_document_list"
    CATALOG_DOCUMENT_COUNT = "catalog_document_count"
    METADATA_FILTERED_RAG = "metadata_filtered_rag"
    PURE_RAG = "pure_rag"
    ARTIFACT_REQUEST = "artifact_request"
    INGESTION_ACTION = "ingestion_action"
    DOCUMENT_MANAGEMENT_ACTION = "document_management_action"
    UNKNOWN = "unknown"

class IntentDetector:
    _schema_cache = None
    _schema_cache_time = 0
    CACHE_TTL = 300  # 5 minutes

    CATALOG_LIST_REGEX = re.compile(r"^(?i)(list|show me all|what are the)\b.*(documents|files|records)")
    CATALOG_COUNT_REGEX = re.compile(r"^(?i)(how many|count)\b.*(documents|files|records)")
    FILTER_REGEX = re.compile(r"(?i)@([a-zA-Z0-9_]+):([a-zA-Z0-9_]+)|in\s+([a-zA-Z0-9_]+)\s*(?:=|:)\s*([a-zA-Z0-9_]+)")

    @classmethod
    async def _get_schema(cls):
        now = time.time()
        if cls._schema_cache and (now - cls._schema_cache_time) < cls.CACHE_TTL:
            return cls._schema_cache
        try:
            schema = await core_client.get_metadata_schema()
            cls._schema_cache = schema
            cls._schema_cache_time = now
            return schema
        except Exception as e:
            logger.warning(f"Failed to fetch metadata schema: {e}")
            return None

    @classmethod
    async def analyze(cls, message: str) -> tuple[str, dict]:
        """
        Analyzes the message and returns the detected intent and extracted metadata.
        """
        # Fetch schema to know valid keys
        schema = await cls._get_schema()
        valid_keys = set()
        if schema and isinstance(schema, dict):
            if "properties" in schema:
                valid_keys = set(schema["properties"].keys())
            else:
                valid_keys = set(schema.keys())
        
        extracted_metadata = {}

        # 1. Regex fallback
        match = cls.FILTER_REGEX.search(message)
        if match:
            if match.group(1) and match.group(2):
                key, value = match.group(1), match.group(2)
            else:
                key, value = match.group(3), match.group(4)
            extracted_metadata[key.lower()] = value

        # 2. Known keys extraction (e.g., project=apollo, department=r&d)
        kv_regex = re.compile(r"(?i)\b([a-zA-Z0-9_]+)\s*(?:=|:)\s*([a-zA-Z0-9_&]+)\b")
        for k, v in kv_regex.findall(message):
            k_lower = k.lower()
            if valid_keys and k_lower in valid_keys:
                extracted_metadata[k_lower] = v

        # 3. Field-value extraction without punctuation (e.g., "project apollo" or "apollo project")
        if valid_keys:
            keys_pattern = "|".join(re.escape(k) for k in valid_keys)
            field_value_regex = re.compile(rf"(?i)\b({keys_pattern})\s+([a-zA-Z0-9_&]+)\b")
            for k, v in field_value_regex.findall(message):
                extracted_metadata[k.lower()] = v
                
            value_field_regex = re.compile(rf"(?i)\b([a-zA-Z0-9_&]+)\s+({keys_pattern})\b")
            for v, k in value_field_regex.findall(message):
                if k.lower() not in extracted_metadata:
                    extracted_metadata[k.lower()] = v

        from retriva_gateway.core.context import get_correlation_id
        corr_id = get_correlation_id() or "unknown"

        if cls.CATALOG_COUNT_REGEX.search(message):
            logger.info(f"[{corr_id}] Intent detected: catalog_document_count, filters: {extracted_metadata}")
            return Intent.CATALOG_DOCUMENT_COUNT, extracted_metadata
            
        if cls.CATALOG_LIST_REGEX.search(message):
            logger.info(f"[{corr_id}] Intent detected: catalog_document_list, filters: {extracted_metadata}")
            return Intent.CATALOG_DOCUMENT_LIST, extracted_metadata

        if extracted_metadata:
            logger.info(f"[{corr_id}] Intent detected: metadata_filtered_rag, filters: {extracted_metadata}")
            return Intent.METADATA_FILTERED_RAG, extracted_metadata
            
        logger.info(f"[{corr_id}] Intent detected: pure_rag")
        return Intent.PURE_RAG, {}
