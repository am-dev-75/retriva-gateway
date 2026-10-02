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

"""Spec 001 Phase E — streaming gate tests (C5/7b; §Streaming policy).

The deterministic engine ONLY drives the streaming decision: never the
classifier, never the registry, never the agent loop, never a tool, and
no mutation claim.  Covers the three closed outcomes of
``classify_streaming_message`` (REFUSE_STREAM / STREAM_CLARIFY /
RAG_PASSTHROUGH) and the chat helpers that render them
(``_streaming_refusal`` typed 409; ``_streaming_clarification`` neutral
SSE).  The classifier is structurally bypassed — these tests assert that.
"""

from __future__ import annotations

import json

from fastapi.responses import StreamingResponse

from retriva_gateway.api.v2 import chat as chat_module
from retriva_gateway.core.routing import classify_streaming_message
from retriva_gateway.core.routing.pipeline import StreamingDecision


# ---------------------------------------------------------------------------
# classify_streaming_message — deterministic engine only
# ---------------------------------------------------------------------------

def test_explicit_workflow_command_refuses_streaming():
    decision, family, _ = classify_streaming_message("Activate acpver_123.")
    assert decision is StreamingDecision.REFUSE_STREAM
    assert family == "ACP"


def test_safe_proposal_command_refuses_streaming():
    decision, family, _ = classify_streaming_message("Propose a new ACP cohort")
    assert decision is StreamingDecision.REFUSE_STREAM
    assert family == "ACP"


def test_workflow_adjacent_ambiguity_streams_clarification():
    decision, _, res = classify_streaming_message("Handle the import.")
    assert decision is StreamingDecision.STREAM_CLARIFY
    assert res.intent.value == "AMBIGUOUS"


def test_followup_context_streams_clarification():
    decision, _, res = classify_streaming_message("Approve it.")
    assert decision is StreamingDecision.STREAM_CLARIFY
    # The engine detected a follow-up shape (Phase C ownership upstream).
    assert "FOLLOWUP_CONTEXT" in [c.value for c in res.reason_codes]


def test_multi_intent_streams_clarification():
    decision, _, _ = classify_streaming_message(
        "Approve acpver_1 and activate acpver_2.")
    assert decision is StreamingDecision.STREAM_CLARIFY


def test_informational_streaming_passthrough():
    decision, _, _ = classify_streaming_message(
        "How does ACP activation work?")
    assert decision is StreamingDecision.RAG_PASSTHROUGH


def test_non_adjacent_ambiguous_streaming_passthrough():
    # "Yes." is non-adjacent ambiguity — unchanged cited SSE RAG, never
    # a clarification or refusal.
    decision, _, _ = classify_streaming_message("Yes.")
    assert decision is StreamingDecision.RAG_PASSTHROUGH


# ---------------------------------------------------------------------------
# Chat helpers — rendered gate responses (no classifier, no tool)
# ---------------------------------------------------------------------------

def test_streaming_refusal_is_typed_409_with_retry_contract():
    resp = chat_module._streaming_refusal("ACP", "corr-1")
    assert resp.status_code == 409
    body = json.loads(resp.body)
    detail = body["detail"]
    assert detail["code"] == "workflow_stream_unsupported"
    assert "non_streaming" == detail["retry"]["mode"]
    assert detail["retry"]["endpoint"] == "/api/v2/chat"
    assert detail["workflow_family"] == "ACP"
    # Never leaks raw content, tool arguments, or identifiers.
    blob = json.dumps(detail)
    for forbidden in ("acpver", "token", "Bearer", "secret", "resource"):
        assert forbidden not in blob


def test_streaming_refusal_omits_family_when_unknown():
    resp = chat_module._streaming_refusal(None, "corr-2")
    body = json.loads(resp.body)
    assert "workflow_family" not in body["detail"]


def test_streaming_clarification_is_neutral_sse():
    import asyncio

    _, _, result = classify_streaming_message("Handle the import.")
    resp = chat_module._streaming_clarification("corr-3", result)
    assert isinstance(resp, StreamingResponse)
    assert resp.media_type == "text/event-stream"

    async def _collect():
        out = []
        async for chunk in resp.body_iterator:
            out.append(chunk)
        return b"".join(out)

    text = asyncio.run(_collect()).decode()
    # Opens with the role announcement and closes with [DONE]; the
    # established `data: {chunk}` shape, no new event type.
    assert text.startswith("data: ")
    assert "data: [DONE]" in text
    # No classifier call, no tool, no execution claim in the stream.
    assert "acpver" not in text and "Bearer" not in text
