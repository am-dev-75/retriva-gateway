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

"""Incident 2026-11-05 regression: natural approval -> governed import.

The owner's second turn ("Ho revisionato e approvato il batch. Il suo
timestamp e 2026-11-02T15:29:00+01:00.") must be able to continue the
staged historical import: four row decisions with the exact timestamp,
batch approval, then an idempotent commit.  It must also never produce an
empty assistant message.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from retriva_gateway.agent import tools as tools_mod
from retriva_gateway.agent.loop import run_agent_loop
from retriva_gateway.agent.tools import (
    ToolContext,
    ToolExecutionError,
    _require_campaign_import_intent,
    _split_addressed_at,
    build_default_tool_registry,
    load_session_import_context,
)

BATCH_ID = "ibth_286841b0ec6249fd"
SESSION_ID = "816d23a0-4679-404b-bbcc-96f42b34f78d"
ROWS = ["irow_r1", "irow_r2", "irow_r3", "irow_r4"]
TIMESTAMP = "2026-11-02T15:29:00+01:00"
MESSAGE = (
    "Ho revisionato e approvato il batch. "
    "Il suo timestamp e 2026-11-02T15:29:00+01:00."
)
IDEMPOTENCY_KEY = "chat-ibth_286841b0ec6249fd-20261102T152900"


def _context(message: str = MESSAGE) -> ToolContext:
    return ToolContext(
        session_id=SESSION_ID,
        kb_id="cust_0007",
        allowed_attachment_ids=["att_1"],
        correlation_id="corr_incident",
        user_message=message,
        import_batch_context={
            "batch_id": BATCH_ID,
            "status": "APPROVED",
            "campaign_code": "2026-CRA-IT",
            "rows": [
                {
                    "row_id": row_id,
                    "source_row": index + 2,
                    "disposition": "CREATE_ORGANIZATION",
                    "addressed_date": None,
                }
                for index, row_id in enumerate(ROWS)
            ],
        },
    )


def _llm_response(content="", tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message, "finish_reason": "stop"}]}


def _tool_call(call_id: str, name: str, arguments: dict):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


# ---------------------------------------------------------------------------
# Guard: the Italian approval is explicit confirmation for THIS batch
# ---------------------------------------------------------------------------

def test_italian_approval_authorizes_trusted_batch_and_rows():
    ctx = _context()
    _require_campaign_import_intent(
        ctx, action="historical-import commit", resource=BATCH_ID,
        allow_batch_anaphor=True)
    for row_id in ROWS:
        _require_campaign_import_intent(
            ctx, action="addressed timestamp decision", resource=row_id,
            allow_batch_anaphor=True, allow_row_context=True,
            require_timestamp=True)


def test_approval_does_not_authorize_another_batch():
    with pytest.raises(ToolExecutionError) as exc:
        _require_campaign_import_intent(
            _context(), action="historical-import commit",
            resource="ibth_someone_else", allow_batch_anaphor=True)
    assert exc.value.code == "explicit_intent_required"


@pytest.mark.parametrize("message", [
    "Il batch e pronto.",
    "Non approvo il batch. Il suo timestamp e 2026-11-02T15:29:00+01:00.",
    "Se approvassi il batch, il timestamp sarebbe 2026-11-02T15:29:00+01:00.",
    "Ho approvato il batch?",
    "\"Ho revisionato e approvato il batch. Il suo timestamp e "
    "2026-11-02T15:29:00+01:00.\"",
])
def test_guard_rejects_non_explicit_or_unsafe_confirmations(message):
    with pytest.raises(ToolExecutionError) as exc:
        _require_campaign_import_intent(
            _context(message), action="historical-import commit",
            resource=BATCH_ID, allow_batch_anaphor=True)
    assert exc.value.code == "explicit_intent_required"


def test_row_decision_requires_an_explicit_timestamp():
    message = "Ho revisionato e approvato il batch."
    with pytest.raises(ToolExecutionError) as exc:
        _require_campaign_import_intent(
            _context(message), action="addressed timestamp decision",
            resource=ROWS[0], allow_batch_anaphor=True,
            allow_row_context=True, require_timestamp=True)
    assert exc.value.code == "invalid_arguments"


def test_addressed_at_is_split_without_substitution():
    assert _split_addressed_at(TIMESTAMP, "Europe/Rome") == (
        "2026-11-02", "15:29:00")
    with pytest.raises(ToolExecutionError) as exc:
        _split_addressed_at(TIMESTAMP, "UTC")
    assert exc.value.code == "invalid_arguments"


# ---------------------------------------------------------------------------
# Session context resolution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_session_import_context_selects_this_session(monkeypatch):
    calls = []

    async def fake_crm(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/api/v2/crm/imports/batches":
            return {"batches": [
                {"import_batch_id": "ibth_other", "source_system":
                 "company_import", "status": "APPROVED"},
                {"import_batch_id": BATCH_ID,
                 "source_system": "campaign_history",
                 "status": "APPROVED"},
            ]}
        if path.endswith(f"/campaigns/import-batches/{BATCH_ID}/rows"):
            return [
                {"row_id": row, "source_row_number": index + 2,
                 "selected_disposition": "CREATE_ORGANIZATION"}
                for index, row in enumerate(ROWS)
            ]
        return {
            "import_batch_id": BATCH_ID,
            "status": "APPROVED",
            "source_session_id": SESSION_ID,
            "summary_jsonb": {
                "campaign_code_normalized": "2026-CRA-IT",
            },
        }

    monkeypatch.setattr(tools_mod, "_crm_request", fake_crm)
    context = await load_session_import_context(SESSION_ID)
    assert context is not None
    assert context["batch_id"] == BATCH_ID
    assert context["campaign_code"] == "2026-CRA-IT"
    assert [row["row_id"] for row in context["rows"]] == ROWS
    assert any(call[1].endswith("/imports/batches") for call in calls)


@pytest.mark.asyncio
async def test_load_session_import_context_fails_closed(monkeypatch):
    async def fake_crm(method, path, **kwargs):
        raise RuntimeError("crm unavailable")

    monkeypatch.setattr(tools_mod, "_crm_request", fake_crm)
    assert await load_session_import_context(SESSION_ID) is None


# ---------------------------------------------------------------------------
# End-to-end: the natural approval drives the governed sequence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_italian_approval_drives_row_decision_approve_commit(
        monkeypatch):
    crm_calls = []

    async def fake_crm(method, path, **kwargs):
        crm_calls.append({"method": method, "path": path,
                          "json": kwargs.get("json")})
        if path.endswith("/decision"):
            return {"ok": True, "row_id": "row"}
        if path.endswith("/approve"):
            return {"ok": True, "status": "APPROVED"}
        if path.endswith("/commit"):
            return {
                "ok": True,
                "counters": {
                    "organizations_created": 4,
                    "memberships_created": 4,
                    "addressed_events_created": 4,
                },
                "chat_summary": (
                    "Committed 4 organizations, 4 memberships, "
                    "4 addressed events."),
            }
        return {"ok": True}

    monkeypatch.setattr(tools_mod, "_crm_request", fake_crm)

    row_calls = [
        _tool_call(f"call_{index}", "review_campaign_history_row", {
            "batch_id": BATCH_ID,
            "row_id": row_id,
            "decision": "set_addressed_date",
            "addressed_at": TIMESTAMP,
            "addressed_timezone": "Europe/Rome",
        })
        for index, row_id in enumerate(ROWS)
    ]
    responses = [
        _llm_response(tool_calls=row_calls),
        _llm_response(tool_calls=[_tool_call(
            "call_approve", "approve_campaign_history_batch",
            {"batch_id": BATCH_ID, "approve_pending": True})]),
        _llm_response(tool_calls=[_tool_call(
            "call_commit", "commit_campaign_history_batch",
            {"batch_id": BATCH_ID,
             "idempotency_key": IDEMPOTENCY_KEY})]),
        _llm_response(content=(
            "Added 4 companies to 2026-CRA-IT: 4 organizations created, "
            "4 memberships, 4 addressed events at "
            "2026-11-02T15:29:00+01:00.")),
    ]

    async def fake_chat(payload, stream=False):
        return responses.pop(0)

    with patch(
        "retriva_gateway.agent.loop.core_client.chat_completions",
        new=AsyncMock(side_effect=fake_chat),
    ):
        result = await run_agent_loop(
            user_message=MESSAGE,
            registry=build_default_tool_registry(),
            ctx=_context(),
            kb_ids=["cust_0007"],
        )

    decision_calls = [c for c in crm_calls if c["path"].endswith("/decision")]
    approve_calls = [c for c in crm_calls if c["path"].endswith("/approve")]
    commit_calls = [c for c in crm_calls if c["path"].endswith("/commit")]

    assert len(decision_calls) == 4
    assert len(approve_calls) == 1
    assert len(commit_calls) == 1
    for call in decision_calls:
        assert call["json"]["decision"] == "set_addressed_date"
        assert call["json"]["addressed_date"] == "2026-11-02"
        assert call["json"]["addressed_time"] == "15:29:00"
        assert call["json"]["addressed_timezone"] == "Europe/Rome"
    assert approve_calls[0]["json"]["approve_pending"] is True
    assert commit_calls[0]["json"]["idempotency_key"] == IDEMPOTENCY_KEY
    assert result.content.strip()
    assert "4 organizations created" in result.content
    assert len(result.tool_calls_executed) == 6
    assert all(item["ok"] for item in result.tool_calls_executed)
