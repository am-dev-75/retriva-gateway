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

import pytest
from unittest.mock import patch
from retriva_gateway.core.intent import Intent, IntentDetector

@pytest.mark.asyncio
async def test_pure_rag():
    intent, meta = await IntentDetector.analyze("What is the meaning of life?")
    assert intent == Intent.PURE_RAG
    assert meta == {}

@pytest.mark.asyncio
async def test_catalog_list():
    intent, meta = await IntentDetector.analyze("list all documents")
    assert intent == Intent.CATALOG_DOCUMENT_LIST
    assert meta == {}

@pytest.mark.asyncio
async def test_catalog_count():
    intent, meta = await IntentDetector.analyze("how many files do we have?")
    assert intent == Intent.CATALOG_DOCUMENT_COUNT
    assert meta == {}

@pytest.mark.asyncio
async def test_metadata_filtered_rag_explicit_syntax():
    intent, meta = await IntentDetector.analyze("what is the status @project:apollo?")
    assert intent == Intent.METADATA_FILTERED_RAG
    assert meta == {"project": "apollo"}

    intent, meta = await IntentDetector.analyze("who is the lead in department:r&d")
    assert intent == Intent.METADATA_FILTERED_RAG
    assert meta == {"department": "r&d"}

@pytest.mark.asyncio
@patch("retriva_gateway.core.intent.core_client.get_metadata_schema")
async def test_metadata_filtered_rag_dynamic_schema(mock_schema):
    # Mock schema return
    mock_schema.return_value = {
        "properties": {
            "project": {"type": "string"},
            "department": {"type": "string"}
        }
    }
    
    # Test project=apollo
    intent, meta = await IntentDetector.analyze("what is going on with project=apollo")
    assert intent == Intent.METADATA_FILTERED_RAG
    assert meta == {"project": "apollo"}

    # Test department r&d
    intent, meta = await IntentDetector.analyze("status for department:r&d")
    assert intent == Intent.METADATA_FILTERED_RAG
    assert meta == {"department": "r&d"}
