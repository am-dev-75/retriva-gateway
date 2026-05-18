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

import asyncio
from retriva_gateway.core.intent import Intent, IntentDetector

# Mock schema
async def mock_get_schema():
    return {
        "properties": {
            "project": {"type": "string"},
            "department": {"type": "string"}
        }
    }

IntentDetector._get_schema = mock_get_schema

async def run_tests():
    # 'List all documents for project apollo' is classified as catalog_document_list.
    i, m = await IntentDetector.analyze("List all documents for project apollo")
    assert i == Intent.CATALOG_DOCUMENT_LIST, f"Failed: {i}"
    assert m == {"project": "apollo"}, f"Failed meta: {m}"

    # 'List all the documents you have dealing with apollo project' is classified as catalog_document_list.
    i, m = await IntentDetector.analyze("List all the documents you have dealing with apollo project")
    assert i == Intent.CATALOG_DOCUMENT_LIST, f"Failed: {i}"
    assert m == {"project": "apollo"}, f"Failed meta: {m}"

    # 'How many documents are tagged project apollo?' is classified as catalog_document_count.
    i, m = await IntentDetector.analyze("How many documents are tagged project apollo?")
    assert i == Intent.CATALOG_DOCUMENT_COUNT, f"Failed: {i}"
    assert m == {"project": "apollo"}, f"Failed meta: {m}"

    # 'What are the costs for project apollo?' is classified as metadata_filtered_rag.
    i, m = await IntentDetector.analyze("What are the costs for project apollo?")
    assert i == Intent.METADATA_FILTERED_RAG, f"Failed: {i}"
    assert m == {"project": "apollo"}, f"Failed meta: {m}"

    print("All tests passed!")

asyncio.run(run_tests())
