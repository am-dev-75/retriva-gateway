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

"""Spec 038 Phase 5 — campaign-governance chat tools, intent routing and
destructive-action guards (deterministic; mocked CRM transport)."""

from __future__ import annotations

import json
from typing import Any, Dict

import httpx
import pytest

from retriva_gateway.agent import tools as tools_mod
from retriva_gateway.agent.tools import (
    ToolContext,
    ToolExecutionError,
    build_campaign_governance_tools,
)
from retriva_gateway.core.routing import classify_streaming_message
from retriva_gateway.core.routing.deterministic import DeterministicEngine
from retriva_gateway.core.routing.guards import evaluate_consequential_guard
from retriva_gateway.core.routing.pipeline import StreamingDecision
from retriva_gateway.core.routing.policy import is_consequential, is_safe_workflow
from retriva_gateway.core.routing.taxonomy import (
    Explicitness,
    Intent,
    InteractionMode,
)

ENGINE = DeterministicEngine()

CONSEQUENTIAL_TOOLS = {
    "revoke_addressed_event",
    "review_campaign_history_row",
    "approve_campaign_history_batch",
    "commit_campaign_history_batch",
    "amend_campaign_history",
    "approve_grace_policy",
    "activate_grace_policy",
    "revoke_grace_policy",
    "approve_campaign_exclusion",
    "activate_campaign_exclusion",
    "revoke_campaign_exclusion",
    "supersede_campaign_exclusion",
    "expire_campaign_exclusion",
}


def _ctx(message: str) -> ToolContext:
    return ToolContext(session_id="sess_t", kb_id="default",
                       correlation_id="corr_t", user_message=message)


class TestRouting:
    @pytest.mark.parametrize("message,intent,mode", [
        ("Activate exclusion excl_1", Intent.CAMPAIGN_EXCLUSION_ACTIVATION,
         InteractionMode.DESTRUCTIVE_MUTATION),
        ("Approve the grace policy gpol_1",
         Intent.CAMPAIGN_SETTINGS_APPROVAL,
         InteractionMode.DESTRUCTIVE_MUTATION),
        ("Commit the campaign history import batch ibth_1",
         Intent.CAMPAIGN_HISTORY_COMMIT,
         InteractionMode.DESTRUCTIVE_MUTATION),
        ("Amend historical event cev_1",
         Intent.CAMPAIGN_HISTORY_AMEND,
         InteractionMode.DESTRUCTIVE_MUTATION),
        ("Propose excluding competitors",
         Intent.CAMPAIGN_EXCLUSION_PROPOSAL, InteractionMode.ANALYSIS),
        ("Review exclusion excl_1", Intent.CAMPAIGN_EXCLUSION_REVIEW,
         InteractionMode.ANALYSIS),
        ("Show eligibility for org_1", Intent.CAMPAIGN_ELIGIBILITY,
         InteractionMode.ANALYSIS),
        ("Show the campaign lineage for 2026-X", Intent.CAMPAIGN_LINEAGE,
         InteractionMode.ANALYSIS),
        ("Revoke the addressed event cev_1",
         Intent.CAMPAIGN_ADDRESSED_REVOCATION,
         InteractionMode.DESTRUCTIVE_MUTATION),
        ("List exclusions", Intent.CAMPAIGN_EXCLUSION_LIST,
         InteractionMode.ANALYSIS),
        ("Preview the impact of exclusion excl_1",
         Intent.CAMPAIGN_EXCLUSION_IMPACT, InteractionMode.ANALYSIS),
    ])
    def test_campaign_governance_messages_route(self, message, intent,
                                                mode):
        result = ENGINE.classify(message)
        assert result.intent is intent
        assert result.mode is mode

    @pytest.mark.parametrize("message,intent", [
        ("Approve the campaign audience run_1",
         Intent.CAMPAIGN_AUDIENCE_APPROVAL),
        ("Show me the campaign audience",
         Intent.CAMPAIGN_AUDIENCE_ANALYSIS),
        ("Import the campaign history file",
         Intent.CAMPAIGN_HISTORY_IMPORT),
        ("Approve the ACP version acpver_1", Intent.ACP_APPROVAL),
    ])
    def test_accepted_routing_is_preserved(self, message, intent):
        assert ENGINE.classify(message).intent is intent

    @pytest.mark.parametrize("message,intent", [
        ("Show the company import batch ibth_1",
         Intent.COMPANY_IMPORT_STATUS),
        ("Review the company import batch ibth_1",
         Intent.COMPANY_IMPORT_REVIEW),
        ("Commit the company import batch ibth_1",
         Intent.COMPANY_IMPORT_COMMIT),
        ("Show me the campaign audience",
         Intent.CAMPAIGN_AUDIENCE_ANALYSIS),
        ("Approve the campaign audience run_1",
         Intent.CAMPAIGN_AUDIENCE_APPROVAL),
    ])
    def test_history_vocabulary_does_not_steal_accepted_routing(
            self, message, intent):
        assert ENGINE.classify(message).intent is intent

    @pytest.mark.parametrize("message", [
        "Was the exclusion excl_1 activated?",
        "Has the grace policy gpol_1 been revoked?",
        "Which exclusion excl_1 was approved?",
    ])
    def test_interrogative_framing_never_routes_destructive(self, message):
        result = ENGINE.classify(message)
        if result.intent is not None:
            assert result.intent not in CONSEQUENTIAL_INTENTS_FOR_TEST

    def test_generic_commit_batch_is_not_stolen(self):
        result = ENGINE.classify("Commit the batch.")
        assert result.intent is not Intent.CAMPAIGN_HISTORY_COMMIT

    @pytest.mark.parametrize("message", [
        "Don't activate exclusion excl_1",
        "Do not approve the grace policy gpol_1",
        "How do I activate an exclusion?",
        "Show me how to revoke a grace policy",
        "Write me a prompt to commit the campaign history import",
        '"Activate exclusion excl_1"',
    ])
    def test_non_authorizing_framings_never_route_to_destructive(
            self, message):
        result = ENGINE.classify(message)
        if result.intent is None:
            return
        assert result.intent not in CONSEQUENTIAL_INTENTS_FOR_TEST

    def test_consequential_guard_requires_explicit_resource(self):
        ok = ENGINE.classify("Activate exclusion excl_1")
        assert ok.explicitness is Explicitness.EXPLICIT
        assert evaluate_consequential_guard(ok).passed is True
        missing = ENGINE.classify("Activate the exclusion")
        guard = evaluate_consequential_guard(missing)
        assert guard.passed is False

    def test_consequential_intents_are_not_classifier_safe(self):
        for intent in CONSEQUENTIAL_INTENTS_FOR_TEST:
            assert is_consequential(intent)
            assert not is_safe_workflow(intent)
        for intent in (Intent.CAMPAIGN_EXCLUSION_LIST,
                       Intent.CAMPAIGN_EXCLUSION_PROPOSAL,
                       Intent.CAMPAIGN_EXCLUSION_REVIEW,
                       Intent.CAMPAIGN_SETTINGS_STATUS,
                       Intent.CAMPAIGN_SETTINGS_DRAFT,
                       Intent.CAMPAIGN_SETTINGS_SUBMIT,
                       Intent.CAMPAIGN_SETTINGS_REVIEW,
                       Intent.CAMPAIGN_HISTORY_STATUS,
                       Intent.CAMPAIGN_ELIGIBILITY,
                       Intent.CAMPAIGN_LINEAGE):
            assert is_safe_workflow(intent)
            assert not is_consequential(intent)

    @pytest.mark.parametrize("message", [
        "Activate exclusion excl_1",
        "Approve the grace policy gpol_1",
        "Commit the campaign history import batch ibth_1",
    ])
    def test_streaming_never_streams_rag_for_consequential(self, message):
        decision, _routed, _res = classify_streaming_message(message)
        assert decision is not StreamingDecision.RAG_PASSTHROUGH


CONSEQUENTIAL_INTENTS_FOR_TEST = {
    Intent.CAMPAIGN_SETTINGS_APPROVAL,
    Intent.CAMPAIGN_SETTINGS_ACTIVATION,
    Intent.CAMPAIGN_SETTINGS_REVOCATION,
    Intent.CAMPAIGN_EXCLUSION_APPROVAL,
    Intent.CAMPAIGN_EXCLUSION_ACTIVATION,
    Intent.CAMPAIGN_EXCLUSION_REVOCATION,
    Intent.CAMPAIGN_EXCLUSION_SUPERSESSION,
    Intent.CAMPAIGN_EXCLUSION_EXPIRY,
    Intent.CAMPAIGN_HISTORY_COMMIT,
    Intent.CAMPAIGN_HISTORY_AMEND,
    Intent.CAMPAIGN_ADDRESSED_REVOCATION,
}


class TestToolInventory:
    def test_inventory_and_closed_schemas(self):
        tools = build_campaign_governance_tools()
        names = {t.name for t in tools}
        assert len(names) == len(tools) == 35
        assert CONSEQUENTIAL_TOOLS <= names
        for tool in tools:
            assert tool.parameters["additionalProperties"] is False
            props = set(tool.parameters["properties"])
            for forbidden in ("tenant", "tenant_id", "url", "sql",
                              "path", "provider", "model",
                              "collection", "kb_id"):
                assert forbidden not in props, (tool.name, forbidden)
        by_name = {t.name: t for t in tools}
        assert by_name["propose_campaign_exclusion"].\
            parameters["additionalProperties"] is False
        assert "scope_type" not in by_name["propose_campaign_exclusion"].\
            parameters["properties"]
        # OFFERING_FAMILY is never a mutable scope on any tool.
        for tool in tools:
            assert "OFFERING_FAMILY" not in json.dumps(tool.parameters)

    def test_destructive_classification(self):
        by_name = {t.name: t for t in build_campaign_governance_tools()}
        for name in CONSEQUENTIAL_TOOLS:
            assert by_name[name].destructive is True, name
        for name in ("get_campaign", "list_campaign_exclusions",
                     "preview_campaign_exclusion_impact",
                     "propose_campaign_exclusion",
                     "review_campaign_exclusion",
                     "create_grace_policy_draft"):
            assert by_name[name].destructive is False, name


@pytest.fixture()
def crm_calls(monkeypatch):
    calls = []

    async def fake(method, path, **kwargs):
        calls.append({"method": method, "path": path,
                      "json": kwargs.get("json"),
                      "params": kwargs.get("params")})
        return {"ok": True, "exclusion_id": "excl_out",
                "status": "PENDING_REVIEW",
                "review_url": "/api/v2/crm/imports/batches/b1/review"}

    monkeypatch.setattr(tools_mod, "_crm_request", fake)
    return calls


class TestToolExecution:
    @pytest.mark.asyncio
    async def test_read_tools_call_the_fixed_crm_paths(self, crm_calls):
        by_name = {t.name: t for t in build_campaign_governance_tools()}
        await by_name["list_campaign_exclusions"].execute(
            {"limit": 10, "cursor": "c|d"},
            _ctx("List the exclusions"))
        assert crm_calls[-1]["method"] == "GET"
        assert crm_calls[-1]["path"] == "/api/v2/crm/campaigns/exclusions"
        await by_name["list_competitor_proposal_signals"].execute(
            {}, _ctx("Show competitor signals"))
        assert crm_calls[-1]["path"] == \
            "/api/v2/crm/campaigns/exclusions/competitor-signals"
        await by_name["get_campaign_history_batch"].execute(
            {"batch_id": "ibth_1"}, _ctx("Show import batch ibth_1"))
        assert crm_calls[-1]["path"] == \
            "/api/v2/crm/campaigns/import-batches/ibth_1"
        out = await by_name["get_campaign_history_batch"].execute(
            {"batch_id": "ibth_1"}, _ctx("Show import batch ibth_1"))
        assert out["review_url"].startswith("http") or \
            out["review_url"].startswith("/")

    @pytest.mark.asyncio
    async def test_create_grace_draft_defaults_duration_in_crm(
            self, crm_calls):
        by_name = {t.name: t for t in build_campaign_governance_tools()}
        tool = by_name["create_grace_policy_draft"]
        assert tool.parameters["required"] == ["timezone"]
        await tool.execute({"timezone": "UTC"},
                           _ctx("Create a grace policy draft"))
        assert crm_calls[-1]["method"] == "PUT"
        assert crm_calls[-1]["path"] == \
            "/api/v2/crm/campaigns/grace-policy"
        assert crm_calls[-1]["json"] == {"timezone": "UTC"}

    @pytest.mark.asyncio
    async def test_proposal_never_activates(self, crm_calls):
        by_name = {t.name: t for t in build_campaign_governance_tools()}
        result = await by_name["propose_campaign_exclusion"].execute(
            {"organization_id": "org_1", "reason_code": "COMPETITOR"},
            _ctx("Exclude competitors from all campaigns"))
        assert crm_calls[-1]["method"] == "POST"
        assert crm_calls[-1]["path"] == "/api/v2/crm/campaigns/exclusions"
        assert "activate" not in crm_calls[-1]["path"]
        assert "PENDING_REVIEW" in result["chat_summary"]

    @pytest.mark.asyncio
    async def test_framing_vetoes_block_descriptive_and_quoted_text(
            self, crm_calls):
        by_name = {t.name: t for t in build_campaign_governance_tools()}
        activate = by_name["activate_campaign_exclusion"]
        for message in ("The exclusion excl_1 was activated yesterday",
                        "I have activated the exclusion excl_1",
                        "The operator said to activate exclusion excl_1",
                        "This would activate exclusion excl_1",
                        "We might activate exclusion excl_1",
                        "Per the ticket: activate exclusion excl_1"):
            with pytest.raises(ToolExecutionError) as exc:
                await activate.execute({"exclusion_id": "excl_1"},
                                       _ctx(message))
            assert exc.value.code == "explicit_intent_required", message
        long_quote = ('"' + 'please activate exclusion excl_1 ' * 40 + '"')
        with pytest.raises(ToolExecutionError):
            await activate.execute({"exclusion_id": "excl_1"},
                                   _ctx(long_quote))
        # A subject-first past description is never routed destructively.
        result = ENGINE.classify(
            "The exclusion excl_1 was activated yesterday")
        assert result.intent not in CONSEQUENTIAL_INTENTS_FOR_TEST
        # Legitimate imperative requests still pass.
        await activate.execute({"exclusion_id": "excl_1"},
                               _ctx("Could you activate exclusion excl_1?"))
        assert crm_calls[-1]["path"].endswith("/excl_1/activate")

    @pytest.mark.asyncio
    async def test_explicit_intent_is_required_for_each_consequential_tool(
            self, crm_calls):
        by_name = {t.name: t for t in build_campaign_governance_tools()}
        cases = {
            "revoke_addressed_event": {
                "campaign": "2026-X", "organization_id": "org_1",
                "event_id": "cev_1", "reason_text": "r",
                "source_system": "s", "source_record_id": "sr"},
            "approve_campaign_history_batch": {"batch_id": "ibth_1"},
            "commit_campaign_history_batch": {
                "batch_id": "ibth_1", "idempotency_key": "k1"},
            "amend_campaign_history": {
                "campaign": "2026-X", "target_event_id": "cev_1",
                "reason_text": "r", "idempotency_key": "k2"},
            "review_campaign_history_row": {
                "batch_id": "ibth_1", "row_id": "irow_1",
                "decision": "exclude_row"},
            "rollback_grace_policy": {"grace_policy_id": "gpol_1"},
            "approve_grace_policy": {"grace_policy_id": "gpol_1"},
            "activate_grace_policy": {"grace_policy_id": "gpol_1"},
            "revoke_grace_policy": {"grace_policy_id": "gpol_1",
                                    "reason_text": "r"},
            "approve_campaign_exclusion": {"exclusion_id": "excl_1"},
            "activate_campaign_exclusion": {"exclusion_id": "excl_1"},
            "revoke_campaign_exclusion": {"exclusion_id": "excl_1",
                                          "reason_text": "r"},
            "supersede_campaign_exclusion": {"exclusion_id": "excl_1"},
            "expire_campaign_exclusion": {"exclusion_id": "excl_1",
                                          "reason_text": "r"},
        }
        for name, args in cases.items():
            for message in ("", "Do it", "Don't do it",
                            "How do I do this?",
                            "If I did it, would it work?"):
                with pytest.raises(ToolExecutionError) as exc:
                    await by_name[name].execute(args, _ctx(message))
                assert exc.value.code == "explicit_intent_required", name
            # Multi-stage requests stop after the first stage.
            with pytest.raises(ToolExecutionError) as exc:
                await by_name[name].execute(
                    args,
                    _ctx("Analyze the import and then commit batch "
                         "ibth_1 for exclusion excl_1 policy gpol_1 "
                         "event cev_1"))
            assert exc.value.code == "explicit_intent_required"
        assert crm_calls == []

    @pytest.mark.asyncio
    async def test_explicit_requests_execute(self, crm_calls):
        by_name = {t.name: t for t in build_campaign_governance_tools()}
        await by_name["activate_campaign_exclusion"].execute(
            {"exclusion_id": "excl_1"},
            _ctx("Activate exclusion excl_1 now"))
        assert crm_calls[-1]["path"] == \
            "/api/v2/crm/campaigns/exclusions/excl_1/activate"
        await by_name["activate_grace_policy"].execute(
            {"grace_policy_id": "gpol_1"},
            _ctx("Activate the grace policy gpol_1"))
        assert crm_calls[-1]["path"] == \
            "/api/v2/crm/campaigns/grace-policy/activate"
        await by_name["commit_campaign_history_batch"].execute(
            {"batch_id": "ibth_1", "idempotency_key": "k1"},
            _ctx("Commit the campaign history import batch ibth_1"))
        assert crm_calls[-1]["path"] == \
            "/api/v2/crm/campaigns/import-batches/ibth_1/commit"
        assert crm_calls[-1]["json"]["idempotency_key"] == "k1"
        await by_name["amend_campaign_history"].execute(
            {"campaign": "2026-X", "target_event_id": "cev_1",
             "reason_text": "correction", "idempotency_key": "amkey123"},
            _ctx("Amend the historical event cev_1"))
        assert crm_calls[-1]["json"]["correction"] == {
            "revokes_event_id": "cev_1"}
        await by_name["rollback_grace_policy"].execute(
            {"grace_policy_id": "gpol_1"},
            _ctx("Roll back the grace policy gpol_1"))
        assert crm_calls[-1]["path"] == \
            "/api/v2/crm/campaigns/grace-policy/gpol_1/rollback"
        await by_name["supersede_campaign_exclusion"].execute(
            {"exclusion_id": "excl_1", "reason_text": "replace"},
            _ctx("Supersede exclusion excl_1"))
        assert crm_calls[-1]["path"] == \
            "/api/v2/crm/campaigns/exclusions/excl_1/supersede"
        assert crm_calls[-1]["json"]["reason_text"] == "replace"

    @pytest.mark.asyncio
    async def test_typed_crm_errors_stay_typed(self, monkeypatch):
        async def failing(method, path, **kwargs):
            request = httpx.Request(method, "http://core" + path)
            response = httpx.Response(
                409, request=request,
                content=b'{"code": "CAMPAIGN_VERSION_CONFLICT", '
                        b'"message": "stale"}',
                headers={"content-type": "application/json"})
            response.raise_for_status()
            return response

        original = tools_mod._crm_request

        async def fake(method, path, **kwargs):
            try:
                await failing(method, path, **kwargs)
            except httpx.HTTPStatusError as e:
                status, code, message = tools_mod._crm_typed_error(
                    e.response)
                raise ToolExecutionError(code, message,
                                         http_status=status)

        monkeypatch.setattr(tools_mod, "_crm_request", fake)
        by_name = {t.name: t for t in build_campaign_governance_tools()}
        with pytest.raises(ToolExecutionError) as exc:
            await by_name["get_campaign_exclusion"].execute(
                {"exclusion_id": "excl_1"}, _ctx("Show exclusion excl_1"))
        assert exc.value.code == "CAMPAIGN_VERSION_CONFLICT"
        assert exc.value.http_status == 409
        monkeypatch.setattr(tools_mod, "_crm_request", original)


class TestPhase6RemediationToolBoundaries:
    @pytest.mark.asyncio
    async def test_review_urls_use_the_configured_trusted_origin(
            self, monkeypatch):
        from retriva_gateway.config import settings
        from retriva_gateway.agent import loop

        async def fake(method, path, **kwargs):
            return {"ok": True, "import_batch_id": "ibth_1",
                    "review_url": "https://evil.example/steal?x=1"}

        monkeypatch.setattr(tools_mod, "_crm_request", fake)
        monkeypatch.setattr(settings, "GATEWAY_PUBLIC_URL",
                            "https://retriva.example")
        by_name = {t.name: t for t in build_campaign_governance_tools()}
        result = await by_name["get_campaign_history_batch"].execute(
            {"batch_id": "ibth_1"}, _ctx("Show batch ibth_1"))
        assert result["review_url"] == (
            "https://retriva.example/api/v2/crm/campaigns/console")
        assert "evil.example" not in result["review_url"]

        async def relative(method, path, **kwargs):
            return {"ok": True, "import_batch_id": "ibth_2",
                    "review_url": "/api/v2/crm/imports/batches/ibth_2/review"}

        monkeypatch.setattr(tools_mod, "_crm_request", relative)
        result = await by_name["get_campaign_history_batch"].execute(
            {"batch_id": "ibth_2"}, _ctx("Show batch ibth_2"))
        assert result["review_url"] == (
            "https://retriva.example/api/v2/crm/imports/batches/"
            "ibth_2/review")

    @pytest.mark.asyncio
    async def test_typed_tool_error_is_not_rewritten_or_rag_fallback(
            self, monkeypatch):
        from retriva_gateway.agent import loop

        async def typed(method, path, **kwargs):
            raise ToolExecutionError(
                "CAMPAIGN_CONCURRENT_ELIGIBILITY_CHANGE",
                "eligibility changed", http_status=409)

        monkeypatch.setattr(tools_mod, "_crm_request", typed)
        by_name = {t.name: t for t in build_campaign_governance_tools()}
        tool = by_name["get_campaign_exclusion"]
        result = await loop._execute_tool(
            tool, {"name": tool.name, "args": {"exclusion_id": "excl_1"}},
            _ctx("Show exclusion excl_1"), 5.0)
        assert result == {"error": {
            "code": "CAMPAIGN_CONCURRENT_ELIGIBILITY_CHANGE",
            "message": "eligibility changed"}}

    @pytest.mark.asyncio
    async def test_unexpected_tool_crash_is_sanitized(self):
        from retriva_gateway.agent import loop
        from retriva_gateway.agent.tools import ToolDefinition

        async def boom(args, ctx):
            raise RuntimeError(
                "SELECT * FROM campaigns.secret /app/src/x.py")

        tool = ToolDefinition(
            name="probe", description="probe", parameters={
                "type": "object", "properties": {},
                "additionalProperties": False},
            execute=boom, destructive=False)
        result = await loop._execute_tool(
            tool, {"name": "probe", "args": {}}, _ctx("probe"), 5.0)
        assert result == {"error": {"code": "tool_crash",
                                    "message": "tool execution failed"}}
        assert "SELECT" not in str(result)


@pytest.mark.asyncio
async def test_absolute_review_url_keeps_run_query(monkeypatch):
    from retriva_gateway.config import settings

    async def fake(method, path, **kwargs):
        return {"ok": True,
                "review_url": "http://internal:9/api/v2/crm/campaigns/"
                              "2026-Q1/audience?run=crun_1&x=2"}

    monkeypatch.setattr(tools_mod, "_crm_request", fake)
    monkeypatch.setattr(settings, "GATEWAY_PUBLIC_URL",
                        "https://retriva.example")
    by_name = {t.name: t for t in build_campaign_governance_tools()}
    result = await by_name["get_campaign_history_batch"].execute(
        {"batch_id": "ibth_1"}, _ctx("Show batch ibth_1"))
    assert result["review_url"] == (
        "https://retriva.example/api/v2/crm/campaigns/2026-Q1/audience"
        "?run=crun_1&x=2")
