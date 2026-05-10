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
from fastapi.testclient import TestClient
from retriva_gateway.main import app
import json
import uuid

client = TestClient(app)

def test_assertions():
    # 1. Gateway starts successfully & /gateway/health returns healthy.
    response = client.get("/gateway/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    
    # 2. /gateway/capabilities returns expected feature flags.
    response = client.get("/gateway/capabilities")
    assert response.status_code == 200
    caps = response.json()
    expected_keys = ["chat", "knowledge_bases", "documents", "ingestion", "artifacts", "folder_upload", "speech_input", "auth"]
    for key in expected_keys:
        assert key in caps
    
    # 3. Knowledge Bases can be listed, created, updated, and deleted through Gateway.
    # List
    response = client.get("/gateway/kbs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    # Create
    response = client.post("/gateway/kbs", json={"id": "test-kb", "name": "Test KB"})
    assert response.status_code == 200
    # Update
    response = client.patch("/gateway/kbs/test-kb", json={"id": "test-kb", "name": "Updated KB"})
    assert response.status_code == 200
    # Delete
    response = client.delete("/gateway/kbs/test-kb")
    assert response.status_code == 200

    # 4. Ingestion batches can be created.
    response = client.post("/gateway/ingestion/batches", json={"metadata": {"test": "val"}})
    assert response.status_code == 200
    batch_id = response.json()["batch_id"]

    # 5. Speech-to-text endpoint is disabled by default but reserved.
    response = client.post("/gateway/speech/transcriptions")
    assert response.status_code == 501

    # 6. Structured logs include correlation IDs.
    response = client.get("/gateway/health", headers={"X-Correlation-ID": "test-id"})
    assert response.headers["X-Correlation-ID"] == "test-id"

    # 7. OpenAPI documentation is available.
    response = client.get("/docs")
    assert response.status_code == 200
