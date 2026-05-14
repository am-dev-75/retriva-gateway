import asyncio
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from retriva_gateway.main import app
from retriva_gateway.core.models import MetadataFilterMode

class TestRouting(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("retriva_gateway.core.client.core_client.retrieval_query")
    @patch("retriva_gateway.core.filters.FilterManager.get_valid_user_keys")
    def test_chat_routing_to_rag(self, mock_keys, mock_retrieval):
        mock_keys.return_value = set()
        mock_retrieval.return_value = {"choices": [{"message": {"content": "hello"}}], "sources": []}
        
        payload = {
            "message": "test message",
            "metadata_filters": [{"field": "project", "operator": "eq", "value": "apollo"}],
            "metadata_filter_mode": "hard"
        }
        
        response = self.client.post("/gateway/chat", json=payload)
        self.assertEqual(response.status_code, 200)
        
        # Verify it called retrieval_query (RAG) and NOT search_documents (Discovery)
        mock_retrieval.assert_called_once()
        args, kwargs = mock_retrieval.call_args
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
