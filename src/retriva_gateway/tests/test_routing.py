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
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from retriva_gateway.main import app
from retriva_gateway.core.models import MetadataFilterMode

class TestRouting(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("retriva_gateway.core.client.core_client.chat_completions")
    @patch("retriva_gateway.core.filters.FilterManager.get_valid_user_keys")
    def test_chat_routing_to_rag(self, mock_keys, mock_chat_completions):
        mock_keys.return_value = set()
        mock_chat_completions.return_value = {"choices": [{"message": {"content": "hello"}}], "sources": []}
        
        payload = {
            "message": "test message",
            "metadata_filters": [{"field": "project", "operator": "eq", "value": "apollo"}],
            "metadata_filter_mode": "hard"
        }
        
        response = self.client.post("/gateway/chat", json=payload)
        self.assertEqual(response.status_code, 200)
        
        # Verify it called chat_completions (RAG) and NOT search_documents (Discovery)
        mock_chat_completions.assert_called_once()
        args, kwargs = mock_chat_completions.call_args
        self.assertEqual(args[0]["metadata_filter_mode"], "hard")

    @patch("retriva_gateway.core.client.core_client.search_documents")
    @patch("retriva_gateway.core.filters.FilterManager.get_valid_user_keys")
    def test_search_routing_to_discovery(self, mock_keys, mock_search):
        mock_keys.return_value = set()
        mock_search.return_value = {"documents": [], "total": 0}
        
        payload = {
            "query": "test query",
            "metadata_filters": [{"field": "project", "operator": "eq", "value": "apollo"}],
            "metadata_filter_mode": "soft"
        }
        
        response = self.client.post("/gateway/documents/search", json=payload)
        self.assertEqual(response.status_code, 200)
        
        # Verify it called search_documents
        mock_search.assert_called_once()
        # Verify metadata_filter_mode is NOT forwarded (discovery ignores it)
        args, kwargs = mock_search.call_args
        core_payload = args[0]
        self.assertNotIn("metadata_filter_mode", core_payload)
        # Verify metadata_filters (tags) ARE forwarded
        self.assertTrue(len(core_payload.get("metadata_filters", [])) > 0)
        # Verify is_discovery is set
        self.assertTrue(core_payload.get("is_discovery"))

    def test_invalid_mode_returns_400(self):
        payload = {
            "message": "test",
            "metadata_filter_mode": "invalid"
        }
        response = self.client.post("/gateway/chat", json=payload)
        # Pydantic validation error since it's an Enum
        self.assertEqual(response.status_code, 422) 

if __name__ == "__main__":
    unittest.main()
