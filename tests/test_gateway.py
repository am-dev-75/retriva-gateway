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

client = TestClient(app)

def test_health():
    response = client.get("/gateway/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "version": "0.1.0"}

def test_capabilities():
    response = client.get("/gateway/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert "chat" in data
    assert "knowledge_bases" in data
    assert "ingestion" in data

def test_kbs_list_create_delete():
    # Initial list should have at least the default KB
    response = client.get("/gateway/kbs")
    assert response.status_code == 200
    initial_list = response.json()
    assert len(initial_list) >= 1
    assert any(kb["id"] == "default" for kb in initial_list)

    # Create a KB
    response = client.post("/gateway/kbs", json={"name": "My New KB", "description": "New description"})
    assert response.status_code == 200
    new_kb = response.json()
    assert new_kb["name"] == "My New KB"
    assert new_kb["id"] == "my-new-kb"

    # Verify listed
    response = client.get("/gateway/kbs")
    assert response.status_code == 200
    current_list = response.json()
    assert any(kb["id"] == "my-new-kb" for kb in current_list)

    # Delete the KB
    response = client.delete(f"/gateway/kbs/my-new-kb")
    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}

    # Verify not listed anymore
    response = client.get("/gateway/kbs")
    assert response.status_code == 200
    assert not any(kb["id"] == "my-new-kb" for kb in response.json())

def test_speech_placeholder():
    response = client.post("/gateway/speech/transcriptions")
    assert response.status_code == 501
