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

"""A historical campaign import must not create a native campaign first."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from retriva_gateway.agent.loop import run_agent_loop
from retriva_gateway.agent.tools import (
    ToolContext,
    ToolDefinition,
    ToolExecutionError,
    ToolRegistry,
    _tool_create_campaign,
)


def _response(content="", tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message, "finish_reason": "stop"}]}


def _call(call_id, name, args):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _registry(seen):
    registry = ToolRegistry()

    async def create(args, ctx):
        seen["create_flag"] = ctx.historical_import_in_turn
        return {"campaign_id": "camp_native"}

    async def import_history(args, ctx):
        seen["import_flag"] = ctx.historical_import_in_turn
        return {"import_batch_id": "ibth_probe"}

    registry.register(ToolDefinition(
        name="create_campaign",
        description="create",
        parameters={"type": "object", "properties": {
            "campaign_code": {"type": "string"},
            "name": {"type": "string"},
        }, "required": ["campaign_code", "name"]},
        execute=create,
    ))
    registry.register(ToolDefinition(
        name="import_campaign_company_history",
        description="import",
        parameters={"type": "object", "properties": {
            "attachment_id": {"type": "string"},
        }, "required": ["attachment_id"]},
        execute=import_history,
    ))
    return registry


@pytest.mark.asyncio
async def test_loop_flags_create_campaign_when_import_is_requested():
    seen = {}
    registry = _registry(seen)
    responses = [
        _response(tool_calls=[
            _call("call_create", "create_campaign",
                  {"campaign_code": "2026-CRA-It-SPS",
                   "name": "Parma campaign"}),
            _call("call_import", "import_campaign_company_history",
                  {"attachment_id": "att_probe"}),
        ]),
        _response(content="Import staged for review."),
    ]
    chat = AsyncMock(side_effect=responses)
    with patch(
            "retriva_gateway.agent.loop.core_client.chat_completions",
            new=chat):
        result = await run_agent_loop(
            user_message="Import the attached campaign history.",
            registry=registry,
            ctx=ToolContext(session_id="sess_probe", kb_id="cust_probe",
                            allowed_attachment_ids=["att_probe"]),
            kb_ids=["cust_probe"],
        )
    assert result.stopped_reason == "final_answer"
    assert seen == {"create_flag": True, "import_flag": True}


@pytest.mark.asyncio
async def test_create_campaign_is_refused_during_an_import_turn():
    ctx = ToolContext(session_id="sess_probe", kb_id="cust_probe",
                      historical_import_in_turn=True)
    with pytest.raises(ToolExecutionError) as excinfo:
        await _tool_create_campaign(
            {"campaign_code": "2026-CRA-It-SPS",
             "name": "Parma campaign"}, ctx)
    assert excinfo.value.code == "campaign_history_import_no_create"
