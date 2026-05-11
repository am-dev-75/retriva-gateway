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

import httpx
from typing import AsyncGenerator, Dict, Any, Optional, List
from retriva_gateway.config import settings
from retriva_gateway.core.context import get_correlation_id
from loguru import logger
import json

class CoreClient:
    def __init__(self):
        self.ingestion_base_url = settings.RETRIVA_CORE_INGESTION_URL
        self.chat_base_url = settings.RETRIVA_CORE_CHAT_URL
        self.timeout = httpx.Timeout(60.0, connect=10.0)

    def _get_headers(self) -> Dict[str, str]:
        headers = {}
        correlation_id = get_correlation_id()
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        return headers

    async def _request(
        self, 
        method: str, 
        base_url: str, 
        path: str, 
        **kwargs
    ) -> httpx.Response:
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        headers = self._get_headers()
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response

    # --- Chat API ---
    async def chat_completions(self, payload: Dict[str, Any], stream: bool = False):
        if stream:
            return self._stream_chat(payload)
        else:
            response = await self._request("POST", self.chat_base_url, "/v1/chat/completions", json=payload)
            return response.json()

    async def _stream_chat(self, payload: Dict[str, Any]) -> AsyncGenerator[bytes, None]:
        url = f"{self.chat_base_url.rstrip('/')}/v1/chat/completions"
        headers = self._get_headers()
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        yield (line + "\n").encode("utf-8")

    # --- KB API ---
    async def list_kbs(self):
        # KB management might be in ingestion or chat? 
        # Usually metadata/discovery is in ingestion v2
        response = await self._request("GET", self.ingestion_base_url, "/api/v2/discovery/collections")
        return response.json()

    async def create_kb(self, payload: Dict[str, Any]):
        response = await self._request("POST", self.ingestion_base_url, "/api/v2/discovery/collections", json=payload)
        return response.json()

    async def delete_kb(self, kb_id: str):
        response = await self._request("DELETE", self.ingestion_base_url, f"/api/v2/discovery/collections/{kb_id}")
        return response.json()

    # --- Documents API ---
    async def list_documents(self, params: Optional[Dict[str, Any]] = None):
        response = await self._request("GET", self.ingestion_base_url, "/api/v2/documents", params=params)
        return response.json()

    async def get_document(self, doc_id: str):
        response = await self._request("GET", self.ingestion_base_url, f"/api/v2/documents/{doc_id}")
        return response.json()

    async def delete_document(self, doc_id: str):
        response = await self._request("DELETE", self.ingestion_base_url, f"/api/v2/documents/{doc_id}")
        return response.json()

    # --- Ingestion API v2 ---
    async def create_ingestion_batch(self, payload: Dict[str, Any]):
        # The ingestion API v2 uses /api/v2/documents for source_uri ingestion
        response = await self._request("POST", self.ingestion_base_url, "/api/v2/documents", json=payload)
        return response.json()

    async def upload_file_to_batch(self, batch_id: str, files: Any, data: Dict[str, Any]):
        # Core v2 ingestion for multipart uploads is at /api/v2/documents/upload
        # batch_id is preserved in user_metadata forwarded in 'data'
        response = await self._request(
            "POST", 
            self.ingestion_base_url, 
            "/api/v2/documents/upload", 
            files=files, 
            data=data
        )
        return response.json()

    async def get_batch_status(self, batch_id: str):
        response = await self._request("GET", self.ingestion_base_url, f"/api/v2/jobs/{batch_id}")
        return response.json()

    # --- Artifacts API v2 ---
    async def list_artifacts(self):
        response = await self._request("GET", self.ingestion_base_url, "/api/v2/artifacts")
        return response.json()

    async def create_artifact(self, payload: Dict[str, Any]):
        response = await self._request("POST", self.ingestion_base_url, "/api/v2/artifacts", json=payload)
        return response.json()

    async def get_artifact(self, artifact_id: str):
        response = await self._request("GET", self.ingestion_base_url, f"/api/v2/artifacts/{artifact_id}")
        return response.json()

    async def download_artifact(self, artifact_id: str) -> httpx.Response:
        # We return the raw response for content download
        return await self._request("GET", self.ingestion_base_url, f"/api/v2/artifacts/{artifact_id}/content")

    async def delete_artifact(self, artifact_id: str):
        response = await self._request("DELETE", self.ingestion_base_url, f"/api/v2/artifacts/{artifact_id}")
        return response.json()

    # --- Metadata API ---
    async def get_metadata_schema(self):
        response = await self._request("GET", self.ingestion_base_url, "/api/v2/metadata/schema")
        return response.json()

    async def get_metadata_values(self, field: str):
        response = await self._request("GET", self.ingestion_base_url, "/api/v2/metadata/values", params={"key": field})
        return response.json()

    async def count_documents(self, params: Optional[Dict[str, Any]] = None):
        response = await self._request("GET", self.ingestion_base_url, "/api/v2/documents/count", params=params)
        return response.json()

    async def filter_documents(self, payload: Dict[str, Any]):
        response = await self._request("POST", self.ingestion_base_url, "/api/v2/documents/filter", json=payload)
        return response.json()

    async def retrieval_query(self, payload: Dict[str, Any]):
        response = await self._request("POST", self.ingestion_base_url, "/api/v2/retrieval/query", json=payload)
        return response.json()

core_client = CoreClient()
