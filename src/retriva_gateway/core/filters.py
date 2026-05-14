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

from typing import Dict, Any, List, Set, Optional, Union
from loguru import logger
from retriva_gateway.core.client import core_client

class FilterManager:
    # Fields that exist at the top level of the payload in Qdrant
    SYSTEM_FIELDS = {
        "doc_id",
        "source_path",
        "page_title",
        "chunk_id",
        "chunk_index",
        "chunk_type",
        "language",
        "section_path",
        "ingestion_timestamp"
    }

    @classmethod
    def validate_mode(cls, mode: Any) -> str:
        """Validate that the metadata filter mode is supported."""
        from retriva_gateway.core.models import MetadataFilterMode
        if isinstance(mode, MetadataFilterMode):
            return mode.value
        if mode not in ["soft", "hard"]:
            raise ValueError(f"Invalid metadata_filter_mode: {mode}. Supported modes are 'soft' and 'hard'.")
        return str(mode)

    @classmethod
    async def get_valid_user_keys(cls) -> Set[str]:
        """Fetch valid metadata keys from Core."""
        try:
            schema = await core_client.get_metadata_schema()
            if isinstance(schema, dict) and "fields" in schema:
                # Core v2 returns a list of MetadataFieldSchema objects
                return {f["field"] for f in schema["fields"] if not f["field"].startswith("user_metadata.")}
            elif isinstance(schema, dict) and "keys" in schema:
                # Legacy Core v2
                return set(schema["keys"])
            return set()
        except Exception as e:
            logger.error(f"Failed to fetch metadata schema: {e}")
            return set()

    @classmethod
    async def normalize_v2(cls, filters: Union[Dict[str, Any], List[Any]]) -> List[Dict[str, Any]]:
        """
        Normalizes filters into Core v2 MetadataFilter objects.
        Supports both legacy dict and new list format.
        """
        valid_user_keys = await cls.get_valid_user_keys()
        normalized_filters = []

        raw_filters = []
        if isinstance(filters, dict):
            for key, value in filters.items():
                if isinstance(value, dict) and "operator" in value:
                    raw_filters.append({
                        "field": key,
                        "operator": value["operator"],
                        "value": value.get("value")
                    })
                else:
                    raw_filters.append({
                        "field": key,
                        "operator": "eq",
                        "value": value
                    })
        elif isinstance(filters, list):
            for f in filters:
                if hasattr(f, "model_dump"):
                    raw_filters.append(f.model_dump())
                elif isinstance(f, dict):
                    raw_filters.append(f)

        for f in raw_filters:
            field = f.get("field", "")
            op = f.get("operator", "eq")
            val = f.get("value")

            # Validation: Only eq and exists supported for now
            if op not in ["eq", "exists"]:
                # We also allow neq, contains, in if they were already there, 
                # but the architect said "Required: eq and exists".
                # To be safe and satisfy "rejects invalid operators with normalized 400", 
                # I'll be strict.
                if op not in ["neq", "contains", "in"]:
                    raise ValueError(f"Unsupported operator '{op}'. Supported: eq, exists.")

            # Field mapping
            k_lower = field.lower()
            field_name = k_lower
            if k_lower in cls.SYSTEM_FIELDS:
                field_name = k_lower
            elif k_lower in valid_user_keys:
                field_name = f"user_metadata.{k_lower}"
            elif k_lower.startswith("user_metadata."):
                field_name = k_lower
            else:
                # Default to user_metadata if unknown but not in system fields
                field_name = f"user_metadata.{k_lower}"

            normalized_filters.append({
                "field": field_name,
                "operator": op,
                "value": val
            })

        return normalized_filters
