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

"""Spec 040 Phase C capability growth: per-campaign addressed stats."""

from __future__ import annotations

import pytest

from retriva_gateway.agent import tools as tools_mod
from retriva_gateway.agent.tools import (
    ToolContext,
    build_default_tool_registry,
)


@pytest.mark.asyncio
async def test_stats_counts_memberships_and_addressed(monkeypatch):
    calls = []

    async def fake_crm(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return [
            {"organization_id": "org_1", "status": "ADDRESSED",
             "addressed_at": "2026-11-02T15:29:00+01:00"},
            {"organization_id": "org_2", "status": "ADDRESSED",
             "addressed_at": "2026-11-02T15:29:00+01:00"},
            {"organization_id": "org_3", "status": "CONSIDERED",
             "addressed_at": None},
        ]

    monkeypatch.setattr(tools_mod, "_crm_request", fake_crm)
    registry = build_default_tool_registry()
    tool = registry.get("get_campaign_company_stats")
    assert tool is not None
    assert tool.destructive is False
    result = await tool.execute(
        {"campaign_code": "2026-CRA-IT"},
        ToolContext(session_id="s", kb_id="k"))
    assert result["memberships"] == 3
    assert result["addressed"] == 2
    assert result["status_counts"] == {"ADDRESSED": 2, "CONSIDERED": 1}
    assert result["truncated"] is False
    assert "2 addressed" in result["chat_summary"]
    assert calls[0][1].endswith("/campaigns/2026-CRA-IT/companies")


@pytest.mark.asyncio
async def test_stats_marks_truncation_at_the_service_bound(monkeypatch):
    async def fake_crm(method, path, **kwargs):
        return [{"status": "ADDRESSED", "addressed_at": "x"}
                for _ in range(2000)]

    monkeypatch.setattr(tools_mod, "_crm_request", fake_crm)
    tool = build_default_tool_registry().get("get_campaign_company_stats")
    result = await tool.execute(
        {"campaign_code": "2026-CRA-IT"},
        ToolContext(session_id="s", kb_id="k"))
    assert result["memberships"] == 2000
    assert result["truncated"] is True
    assert "lower bounds" in result["chat_summary"]


def test_stats_tool_is_campaign_family_and_prompted():
    from retriva_gateway.core.routing.cards import derive_card_map
    from retriva_gateway.agent.loop import AGENT_SYSTEM_PROMPT

    card = derive_card_map()["CAMPAIGN"]
    assert any(tool.name == "get_campaign_company_stats"
               for tool in card.tools)
    assert "get_campaign_company_stats" in AGENT_SYSTEM_PROMPT
    assert "how many companies did we address" in \
        AGENT_SYSTEM_PROMPT.lower()
