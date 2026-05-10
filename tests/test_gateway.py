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

def test_kbs_list():
    response = client.get("/gateway/kbs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_speech_placeholder():
    response = client.post("/gateway/speech/transcriptions")
    assert response.status_code == 501
