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

"""Campaign-companies XLSX export tool (Spec 040 capability growth)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from retriva_gateway.agent import tools as tools_mod
from retriva_gateway.agent.loop import AGENT_SYSTEM_PROMPT
from retriva_gateway.agent.tools import (
    ToolContext,
    build_default_tool_registry,
)
from retriva_gateway.core.routing.cards import derive_card_map


def test_export_tool_is_read_only_and_carded():
    registry = build_default_tool_registry()
    tool = registry.get("export_campaign_companies")
    assert tool is not None
    assert tool.destructive is False
    card = derive_card_map()["CAMPAIGN"]
    assert any(t.name == "export_campaign_companies" for t in card.tools)
    assert "export_campaign_companies" in AGENT_SYSTEM_PROMPT
    assert "export the companies of campaign" in AGENT_SYSTEM_PROMPT.lower()


@pytest.mark.asyncio
async def test_export_stores_artifact_and_returns_download_path(monkeypatch):
    monkeypatch.setattr(
        tools_mod, "_crm_request_bytes",
        AsyncMock(return_value=(b"xlsx-bytes", {
            "x-campaign-companies-count": "446"})))
    response = MagicMock()
    response.json.return_value = {
        "artifact_id": "art_export_1",
        "filename": "art_export_1_campaign-companies-2026-CRA-IT.xlsx",
        "media_type": ("application/vnd.openxmlformats-officedocument."
                       "spreadsheetml.sheet"),
    }
    with patch.object(
            tools_mod.core_client, "_request",
            new=AsyncMock(return_value=response)):
        tool = build_default_tool_registry().get(
            "export_campaign_companies")
        result = await tool.execute(
            {"campaign_code": "2026-CRA-IT"},
            ToolContext(session_id="sess_export", kb_id="cust_0007"))
    assert result["campaign_code"] == "2026-CRA-IT"
    assert result["companies"] == "446"
    assert result["artifact_id"] == "art_export_1"
    assert result["download_path"] == (
        "/api/v2/sessions/sess_export/artifacts/art_export_1/content")
    assert "446" in result["chat_summary"]
    assert "art_export_1" in result["chat_summary"]


@pytest.mark.asyncio
async def test_export_rejects_path_injection():
    tool = build_default_tool_registry().get("export_campaign_companies")
    with pytest.raises(Exception) as exc:
        await tool.execute(
            {"campaign_code": "../other"},
            ToolContext(session_id="sess_export", kb_id="cust_0007"))
    assert getattr(exc.value, "code", "") == "invalid_campaign_code"
