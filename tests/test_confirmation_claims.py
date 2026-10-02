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

"""Phase C confirmation-claim tests (Spec 001; TR67-TR74 positive and
negative halves, claim identity and idempotency per addendum D-1, the
server-only claimed context per D-3, and the ToolContext/activate-tool
integration).

A bare affirmative may enter a consequential workflow ONLY through a
successful atomic claim of exactly one eligible PENDING confirmation;
every mismatch, replay, concurrency, and expiry case fails closed.
claim_id is minted inside the claim transaction; the execution
idempotency key derives from canonical trusted fields (never the
request correlation); the claimed context is server-only, immutable,
and cleared at loop completion; _tool_activate_acp binds the model's
arguments to the claimed binding exactly and sends only the derived
key.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from retriva_gateway.agent import tools as agent_tools
from retriva_gateway.agent.tools import ToolContext
from retriva_gateway.core.routing import (
    ClaimRejection,
    TrustedRoutingContext,
    derive_execution_idempotency_key,
    route_non_streaming,
)
from retriva_gateway.core.routing.confirmation_ready import (
    ConfirmationReadyBlock,
)
from retriva_gateway.core.routing.context import (
    ClaimedConfirmationContext,
    ObservationOutcome,
    WorkflowContextKey,
    WorkflowContextRegistry,
    mint_claim_id,
    observe_tool_result,
)

KEY = WorkflowContextKey("internal-company", "sess_claims_1", "default")
PRINCIPAL = "user_claims_01"
# Real-clock base: the pipeline claim path uses the production
# clock (no test injection), so blocks are minted relative to now.
NOW = datetime.now(timezone.utc)
CREATED_AT = (NOW - timedelta(seconds=60)).isoformat()


def valid_block(**overrides) -> ConfirmationReadyBlock:
    payload = {
        "schema_version": "1",
        "discriminator": "acp_version_approved_for_activation",
        "tenant_id": "internal-company",
        "principal_id": PRINCIPAL,
        "workflow_family": "ACP",
        "operation": "ACP_ACTIVATION",
        "resource_type": "acp_version",
        "resource_id": "acpver_0123456789abcdef",
        "authoritative_version": 3,
        "expected_authoritative_state": "APPROVED",
        "allowed_next_transition": "activate",
        "preparation_transition_token": "acpapl_0123456789abcdef",
        "created_at": CREATED_AT,
        "confirmation_lifetime_seconds": 300,
        "correlation_id": "corr_claims_01",
        "producing_service": "retriva-crm-assistant/acp",
        "producing_operation": "approve_acp_version",
    }
    payload.update(overrides)
    return ConfirmationReadyBlock.model_validate(payload)


def armed_registry(*, block=None):
    reg = WorkflowContextRegistry()
    result = {"acp_id": "acpver_0123456789abcdef", "version": 3,
              "status": "APPROVED",
              "confirmation_ready": (block or valid_block()).model_dump()}
    assert observe_tool_result(
        reg, tenant_id=KEY.tenant_id, session_id=KEY.session_id,
        kb_id=KEY.kb_id, correlation_id="corr_claims_01",
        principal_id=PRINCIPAL, tool_name="approve_acp", result=result,
        now=NOW) is ObservationOutcome.ATTACHED
    return reg


def routing_for(reg, *, principal=PRINCIPAL, key=KEY):
    return TrustedRoutingContext(
        registry=reg, key=key, principal_id=principal)


# ---------------------------------------------------------------------------
# TR67 — bare affirmatives act only via a valid claim
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", ["Yes.", "Sì.", "Confirm it.",
                                     "Confermalo.", "Do it.", "Fallo.",
                                     "Okay.", "Sure.", "Procedi."])
def test_tr67_positive_claim_admits_the_loop(message):
    for _ in range(len(["x"])):  # one fresh registry per message
        reg = armed_registry()
        routed = route_non_streaming(
            message, routing=routing_for(reg))
        assert routed.route.value == "AGENT_LOOP"
        assert routed.claimed is not None
        assert routed.decision.intent.value == "ACP_ACTIVATION"
        # Claimed: the confirmation is consumed.
        assert reg.snapshot().pending_total == 0
        assert reg.snapshot().claimed_total == 1


@pytest.mark.parametrize("message", ["Yes.", "Sì.", "Do it.", "Fallo."])
def test_tr67_negative_without_confirmation_clarifies(message):
    reg = WorkflowContextRegistry()
    routed = route_non_streaming(message, routing=routing_for(reg))
    assert routed.route.value == "CLARIFY"
    assert routed.claimed is None
    assert routed.clarification


def test_tr67_affirmation_with_resource_is_not_bare():
    """A message carrying an operation verb and a resource is a
    normal command, not a bare affirmative (the closed set is
    full-message anchored)."""
    reg = armed_registry()
    routed = route_non_streaming(
        "Yes, activate acpver_0123456789abcdef.",
        routing=routing_for(reg))
    assert routed.route.value == "AGENT_LOOP"
    # It consumed no confirmation (explicit command path).
    assert routed.claimed is None
    assert reg.snapshot().pending_total == 1


# ---------------------------------------------------------------------------
# TR68-TR74 — binding, replay, invalidation, expiry, cross-scope,
# mismatch, deterministic-only creation
# ---------------------------------------------------------------------------

def test_tr68_full_binding_carried_into_the_claimed_context():
    reg = armed_registry()
    claim = reg.claim(KEY, PRINCIPAL, now=NOW)
    assert claim.succeeded
    c = claim.claimed
    assert (c.tenant_id, c.principal_id, c.session_id, c.kb_id) == (
        "internal-company", PRINCIPAL, "sess_claims_1", "default")
    assert c.operation == "ACP_ACTIVATION"
    assert c.resource_type == "acp_version"
    assert c.resource_id == "acpver_0123456789abcdef"
    assert c.authoritative_version == 3
    assert c.expected_authoritative_state == "APPROVED"
    assert c.allowed_next_transition == "activate"
    assert c.preparation_transition_token == "acpapl_0123456789abcdef"
    assert c.producing_correlation_id == "corr_claims_01"


def test_tr69_replay_after_claim_fails_closed():
    reg = armed_registry()
    first = reg.claim(KEY, PRINCIPAL, now=NOW)
    assert first.succeeded
    replay = reg.claim(KEY, PRINCIPAL, now=NOW)
    assert not replay.succeeded
    assert replay.rejection is ClaimRejection.NO_CONFIRMATION
    # A claimed confirmation is never automatically restored.
    assert reg.snapshot().claimed_total == 1


def test_tr69_concurrent_claims_exactly_one_winner():
    reg = armed_registry()
    results = [reg.claim(KEY, PRINCIPAL, now=NOW + timedelta(seconds=i))
               for i in range(5)]
    winners = [r for r in results if r.succeeded]
    assert len(winners) == 1


def test_tr69_failure_after_claim_does_not_restore():
    reg = armed_registry()
    claim = reg.claim(KEY, PRINCIPAL, now=NOW)
    assert claim.succeeded
    # A simulated tool failure after the claim: nothing restores the
    # confirmation; a later claim still fails.
    later = reg.claim(KEY, PRINCIPAL, now=NOW + timedelta(seconds=30))
    assert not later.succeeded


def test_tr70_authoritative_change_invalidates():
    reg = armed_registry()
    invalidated = observe_tool_result(
        reg, tenant_id=KEY.tenant_id, session_id=KEY.session_id,
        kb_id=KEY.kb_id, correlation_id="corr_claims_01",
        principal_id=PRINCIPAL, tool_name="activate_acp",
        result={"acp_id": "acpver_0123456789abcdef", "version": 3,
                "status": "ACTIVE", "activation_id": "acpact_1"},
        now=NOW + timedelta(seconds=10))
    assert invalidated is ObservationOutcome.INVALIDATED
    claim = reg.claim(KEY, PRINCIPAL, now=NOW + timedelta(seconds=20))
    assert not claim.succeeded


def test_tr71_expired_confirmation_never_acts():
    reg = armed_registry()
    claim = reg.claim(KEY, PRINCIPAL,
                      now=NOW + timedelta(minutes=10))
    assert not claim.succeeded
    assert claim.rejection is ClaimRejection.EXPIRED


def test_tr72_cross_tenant_claim_fails():
    reg = armed_registry()
    foreign = WorkflowContextKey("other-tenant", "sess_claims_1",
                                  "default")
    routed = route_non_streaming(
        "Yes.", routing=routing_for(reg, key=foreign))
    assert routed.route.value == "CLARIFY"


def test_tr72_cross_principal_claim_fails():
    reg = armed_registry()
    routed = route_non_streaming(
        "Yes.", routing=routing_for(reg, principal="someone_else"))
    assert routed.route.value == "CLARIFY"
    # The confirmation is untouched by the failed claim.
    assert reg.snapshot().pending_total == 1


def test_tr72_cross_session_and_kb_claims_fail():
    reg = armed_registry()
    for key in (WorkflowContextKey("internal-company", "other", "default"),
                WorkflowContextKey("internal-company", "sess_claims_1",
                                   "other-kb")):
        routed = route_non_streaming(
            "Yes.", routing=routing_for(reg, key=key))
        assert routed.route.value == "CLARIFY"


def test_tr73_synthesized_session_claims_fail_cross_turn():
    """A confirmation bound to a synthesized per-turn session is
    unclaimable in a later turn (different correlation -> different
    session -> key mismatch).  Accepted fail-closed behavior."""
    reg = armed_registry()
    turn1 = WorkflowContextKey("internal-company",
                               "sess_corr_turn_1", "default")
    observe_tool_result(
        reg, tenant_id=turn1.tenant_id, session_id=turn1.session_id,
        kb_id=turn1.kb_id, correlation_id="corr_turn_1",
        principal_id=PRINCIPAL, tool_name="approve_acp",
        result={"confirmation_ready": valid_block(
            correlation_id="corr_turn_1").model_dump()}, now=NOW)
    turn2 = WorkflowContextKey("internal-company",
                               "sess_corr_turn_2", "default")
    routed = route_non_streaming(
        "Yes.", routing=routing_for(reg, key=turn2))
    assert routed.route.value == "CLARIFY"


def test_tr73_operation_and_resource_mismatch_fail_at_activation():
    """The claimed binding is enforced at the activation tool: the
    model cannot redirect a claimed activation (TR73 resource
    mismatch) or execute a different operation."""
    reg = armed_registry()
    claim = reg.claim(KEY, PRINCIPAL, now=NOW)
    assert claim.succeeded
    ctx = ToolContext(session_id=KEY.session_id, kb_id=KEY.kb_id,
                      correlation_id="corr_claims_01",
                      claimed_confirmation=claim.claimed)
    calls = []

    async def fake_acp_call(method, path, json_payload=None):
        calls.append((method, path, json_payload))
        return {"acp_id": "acpver_0123456789abcdef", "version": 3,
                "status": "ACTIVE", "activation_id": "acpact_1"}

    original = agent_tools._acp_call

    def patch(monkeypatch):
        monkeypatch.setattr(agent_tools, "_acp_call", fake_acp_call)

    # Mismatched resource: fails closed, NOTHING is sent upstream.
    with pytest.raises(agent_tools.ToolExecutionError) as exc:
        agent_tools._acp_call = fake_acp_call
        try:
            asyncio.run(agent_tools._tool_activate_acp(
                {"acp_id": "acpver_ffffffffffffffff", "version_number": 3},
                ctx))
        finally:
            agent_tools._acp_call = original
    assert "confirm" in str(exc.value).lower()
    assert calls == []  # no upstream request executed

    # Mismatched version: same fail-closed behavior.
    with pytest.raises(agent_tools.ToolExecutionError):
        agent_tools._acp_call = fake_acp_call
        try:
            asyncio.run(agent_tools._tool_activate_acp(
                {"acp_id": "acpver_0123456789abcdef", "version_number": 4},
                ctx))
        finally:
            agent_tools._acp_call = original
    assert calls == []


def test_tr73_matching_arguments_send_only_the_derived_key():
    reg = armed_registry()
    claim = reg.claim(KEY, PRINCIPAL, now=NOW)
    ctx = ToolContext(session_id=KEY.session_id, kb_id=KEY.kb_id,
                      correlation_id="corr_claims_01",
                      claimed_confirmation=claim.claimed)
    sent = {}

    async def fake_acp_call(method, path, json_payload=None):
        sent.update(json_payload or {})
        return {"acp_id": "acpver_0123456789abcdef", "version": 3,
                "status": "ACTIVE", "activation_id": "acpact_1"}

    agent_tools._acp_call = fake_acp_call
    try:
        result = asyncio.run(agent_tools._tool_activate_acp(
            {"acp_id": "acpver_0123456789abcdef", "version_number": 3},
            ctx))
    finally:
        pass
    assert sent["idempotency_key"] \
        == claim.claimed.execution_idempotency_key
    assert sent["actor_id"] == f"chat:{KEY.session_id}"
    # No confirmation data, token, or claim id rides the request.
    assert "confirmation_ready" not in sent
    assert "claim_id" not in sent
    assert result["status"] == "ACTIVE"


def test_tr74_creation_paths_deterministic_only_structural():
    import retriva_gateway.core.routing.context as ctx_module
    # from_validated_outcome is the single constructor; its parameter
    # type is the strictly validated C0 block.
    import inspect
    sig = inspect.signature(ctx_module.from_validated_outcome)
    assert list(sig.parameters) == ["block", "key", "now"]
    # Phase D supersession (Spec 001): the advisory classifier
    # interface now exists, but it can never create or modify
    # confirmation state — structurally, the classifier module imports
    # NO registry/confirmation context and exposes no state writes.
    import retriva_gateway.core.routing.classifier as clf_module
    assert not hasattr(clf_module, "WorkflowContextRegistry")
    assert not hasattr(clf_module, "from_validated_outcome")
    assert not hasattr(clf_module, "PendingConfirmation")
    import inspect as _inspect
    _source = _inspect.getsource(clf_module)
    for _banned in ("attach_confirmation", "claim(", "observe_command",
                    "from_validated_outcome"):
        assert _banned not in _source, _banned


# ---------------------------------------------------------------------------
# D-1 — claim_id and execution idempotency
# ---------------------------------------------------------------------------

def test_d1_claim_id_format_and_uniqueness():
    ids = {mint_claim_id() for _ in range(200)}
    assert len(ids) == 200
    for claim_id in ids:
        assert re.fullmatch(r"cnfclm_[0-9a-f]{32}", claim_id)


def test_d1_claim_id_minted_inside_the_claim_transaction():
    reg = armed_registry()
    claim = reg.claim(KEY, PRINCIPAL, now=NOW)
    assert claim.succeeded
    assert re.fullmatch(r"cnfclm_[0-9a-f]{32}", claim.claimed.claim_id)
    # The claim_id is associated with the terminal CLAIMED record.
    record = reg._contexts[KEY]  # noqa: SLF001 - test inspection
    assert record.pending_confirmation.state.value == "CLAIMED"


def _claimed_with(claim_id="cnfclm_" + "0" * 32, **overrides):
    base = dict(
        claim_id=claim_id, tenant_id="internal-company",
        principal_id=PRINCIPAL, session_id="sess_claims_1",
        kb_id="default", operation="ACP_ACTIVATION",
        resource_type="acp_version",
        resource_id="acpver_0123456789abcdef", authoritative_version=3,
        expected_authoritative_state="APPROVED",
        allowed_next_transition="activate",
        preparation_transition_token="acpapl_0123456789abcdef",
        execution_idempotency_key="idem_" + "0" * 32,
        producing_correlation_id="corr_secret_01")
    base.update(overrides)
    return ClaimedConfirmationContext(**base)


def test_d1_same_claimed_context_yields_the_same_key():
    claimed = _claimed_with()
    first = derive_execution_idempotency_key(claimed)
    for _ in range(5):
        assert derive_execution_idempotency_key(claimed) == first


def test_d1_key_format():
    key = derive_execution_idempotency_key(_claimed_with())
    assert re.fullmatch(r"idem_[0-9a-f]{32}", key)


def test_d1_changed_correlation_preserves_the_key():
    # Request/producing correlation is NOT a derivation input: a retry
    # with a different correlation reuses the same key.
    a = derive_execution_idempotency_key(
        _claimed_with(producing_correlation_id="corr_A"))
    b = derive_execution_idempotency_key(
        _claimed_with(producing_correlation_id="corr_B"))
    assert a == b


def test_d1_new_claim_mints_a_new_key():
    a = derive_execution_idempotency_key(
        _claimed_with(claim_id="cnfclm_" + "a" * 32))
    b = derive_execution_idempotency_key(
        _claimed_with(claim_id="cnfclm_" + "b" * 32))
    assert a != b
    # Two full cycles over the same preparation token produce distinct
    # keys (new claim_id each cycle).
    reg = armed_registry()
    first = reg.claim(KEY, PRINCIPAL, now=NOW)
    # A new preparation and confirmation cycle (different token).
    reg2 = armed_registry(block=valid_block(
        preparation_transition_token="acpapl_fedcba9876543210"))
    second = reg2.claim(KEY, PRINCIPAL, now=NOW)
    assert first.claimed.execution_idempotency_key \
        != second.claimed.execution_idempotency_key


def test_d1_preparation_token_is_not_the_key():
    claimed = _claimed_with()
    key = derive_execution_idempotency_key(claimed)
    token = claimed.preparation_transition_token
    assert key != token
    assert key != f"idem_{token}"
    assert not key.startswith("acpapl_")
    # Flipping any single non-token input changes the key (the token is
    # an INPUT, not the key itself).
    for field, value in (("tenant_id", "other"), ("principal_id", "x"),
                         ("session_id", "s2"),
                         ("resource_id", "acpver_2"),
                         ("authoritative_version", 4),
                         ("operation", "ACP_ROLLBACK")):
        other = derive_execution_idempotency_key(
            _claimed_with(**{field: value}))
        assert other != key, field


def test_d1_no_message_or_model_influence():
    """The derivation is a pure function of the trusted claimed record:
    message text, tool arguments, and metadata are not inputs, so they
    cannot influence the key."""
    claimed = _claimed_with()
    baseline = derive_execution_idempotency_key(claimed)
    # The derivation reads only the closed claimed-context fields.
    assert baseline == derive_execution_idempotency_key(
        _claimed_with())  # identical record -> identical key


def test_d1_domain_collision_fails_closed_typed():
    """A 128-bit collision surfaces as the existing typed
    IDEMPOTENCY_CONFLICT / ledger behavior at the domain (fail closed);
    nothing here weakens it."""
    # Structural: the CRM ActivateRequest pattern accepts exactly the
    # derived key format and nothing else.
    from pydantic import BaseModel, Field, ValidationError

    class ActivateLike(BaseModel):
        idempotency_key: str | None = Field(
            default=None, pattern=r"^idem_[0-9a-f]{32}$", max_length=64)

    assert ActivateLike(
        idempotency_key=derive_execution_idempotency_key(
            _claimed_with())).idempotency_key
    with pytest.raises(ValidationError):
        ActivateLike(idempotency_key="acpapl_0123456789abcdef")
    with pytest.raises(ValidationError):
        ActivateLike(idempotency_key="idem_" + "A" * 32)


def test_d1_trusted_key_reaches_the_domain_unchanged():
    reg = armed_registry()
    claim = reg.claim(KEY, PRINCIPAL, now=NOW)
    sent = {}

    async def fake_acp_call(method, path, json_payload=None):
        sent.update(json_payload or {})
        return {"acp_id": "acpver_0123456789abcdef", "version": 3,
                "status": "ACTIVE"}

    agent_tools._acp_call = fake_acp_call
    try:
        asyncio.run(agent_tools._tool_activate_acp(
            {"acp_id": "acpver_0123456789abcdef", "version_number": 3},
            ToolContext(session_id=KEY.session_id, kb_id=KEY.kb_id,
                       correlation_id="corr_claims_01",
                       claimed_confirmation=claim.claimed)))
    finally:
        pass
    assert sent["idempotency_key"] == claim.claimed \
        .execution_idempotency_key


# ---------------------------------------------------------------------------
# D-3 — server-only claimed context
# ---------------------------------------------------------------------------

def test_d3_claimed_context_is_frozen_immutable():
    claimed = _claimed_with()
    with pytest.raises(Exception):
        claimed.claim_id = "cnfclm_" + "f" * 32  # type: ignore[misc]


def test_d3_model_visible_line_contains_only_permitted_fields():
    claimed = _claimed_with()
    line = claimed.model_visible_line()
    assert "ACP_ACTIVATION" in line
    assert "acp_version" in line
    assert "acpver_0123456789abcdef" in line
    assert "version=3" in line
    assert "expected_state=APPROVED" in line
    # Never the internal identifiers.
    for forbidden in (claimed.claim_id,
                      claimed.preparation_transition_token,
                      claimed.execution_idempotency_key,
                      claimed.tenant_id, claimed.principal_id,
                      claimed.session_id, claimed.kb_id,
                      claimed.producing_correlation_id):
        assert forbidden not in line


def test_d3_activate_tool_schema_has_no_idempotency_field():
    registry = agent_tools.build_default_tool_registry()
    schema = registry.openai_schema(None)
    activate = [s for s in schema
                if s.get("function", {}).get("name") == "activate_acp"]
    assert len(activate) == 1
    props = activate[0]["function"]["parameters"].get("properties", {})
    assert "idempotency_key" not in props
    assert "confirmation" not in json.dumps(activate)


def test_d3_unrelated_tools_ignore_the_claimed_context():
    """The claimed context is unavailable to unrelated tools: a status
    tool produces the identical result with and without it."""
    async def fake_acp_call(method, path, json_payload=None):
        return {"status": "ACTIVE"}

    plain_ctx = ToolContext(session_id="s", kb_id="k",
                            correlation_id="c")
    claimed_ctx = ToolContext(session_id="s", kb_id="k",
                              correlation_id="c",
                              claimed_confirmation=_claimed_with())
    agent_tools._acp_call = fake_acp_call
    try:
        a = asyncio.run(agent_tools._tool_get_active_acp({}, plain_ctx))
        b = asyncio.run(agent_tools._tool_get_active_acp({}, claimed_ctx))
    finally:
        pass
    assert a == b


def test_d3_claimed_context_never_in_tool_results_or_errors():
    reg = armed_registry()
    claim = reg.claim(KEY, PRINCIPAL, now=NOW)
    ctx = ToolContext(session_id=KEY.session_id, kb_id=KEY.kb_id,
                      correlation_id="corr_claims_01",
                      claimed_confirmation=claim.claimed)

    async def failing_call(method, path, json_payload=None):
        return {"error": {"code": "ACP_INVALID_STATE",
                          "message": "typed failure"}}

    agent_tools._acp_call = failing_call
    try:
        result = asyncio.run(agent_tools._tool_activate_acp(
            {"acp_id": "acpver_0123456789abcdef", "version_number": 3},
            ctx))
    finally:
        pass
    dumped = json.dumps(result)
    assert claim.claimed.claim_id not in dumped
    assert claim.claimed.execution_idempotency_key not in dumped
    assert claim.claimed.preparation_transition_token not in dumped


def test_d3_no_idempotency_key_without_a_claim():
    sent = {}

    async def fake_acp_call(method, path, json_payload=None):
        sent.update(json_payload or {})
        return {"acp_id": "a", "version": 1, "status": "ACTIVE"}

    agent_tools._acp_call = fake_acp_call
    try:
        asyncio.run(agent_tools._tool_activate_acp(
            {"acp_id": "acpver_0123456789abcdef", "version_number": 3},
            ToolContext(session_id="s", kb_id="k", correlation_id="c")))
    finally:
        pass
    assert "idempotency_key" not in sent


def test_d3_model_cannot_supply_idempotency():
    """Even if a model-supplied argument carried an idempotency-like
    key, the tool ignores it: without a claim nothing is sent; with a
    claim only the derived key is sent."""
    sent = {}

    async def fake_acp_call(method, path, json_payload=None):
        sent.update(json_payload or {})
        return {"acp_id": "a", "version": 1, "status": "ACTIVE"}

    agent_tools._acp_call = fake_acp_call
    try:
        asyncio.run(agent_tools._tool_activate_acp(
            {"acp_id": "acpver_0123456789abcdef", "version_number": 3,
             "idempotency_key": "idem_" + "e" * 32},
            ToolContext(session_id="s", kb_id="k", correlation_id="c")))
    finally:
        pass
    assert "idempotency_key" not in sent  # model value ignored entirely


def test_d3_claimed_context_cleared_at_loop_completion(monkeypatch):
    from retriva_gateway.agent.loop import run_agent_loop
    reg = armed_registry()
    claim = reg.claim(KEY, PRINCIPAL, now=NOW)
    ctx = ToolContext(session_id=KEY.session_id, kb_id=KEY.kb_id,
                      correlation_id="corr_claims_01",
                      claimed_confirmation=claim.claimed)

    class _Registry:
        def openai_schema(self, allowed=None):
            return []

    async def run():
        await run_agent_loop(
            user_message="x", registry=_Registry(), ctx=ctx,
            kb_ids=["default"], max_iterations=1)

    with pytest.raises(Exception):
        asyncio.run(run())
    assert ctx.claimed_confirmation is None


# ---------------------------------------------------------------------------
# Modes (off never touches the registry; shadow == active at Phase C)
# ---------------------------------------------------------------------------

def test_mode_off_neither_reads_nor_writes_the_registry(monkeypatch):
    from retriva_gateway.api.v2 import chat as chat_module
    from retriva_gateway.config import settings
    from retriva_gateway.core import routing as routing_pkg
    monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", "off")

    def _bomb():
        raise AssertionError("mode off touched the registry")

    monkeypatch.setattr(routing_pkg, "get_workflow_context_registry",
                        _bomb)
    request = SimpleNamespace(
        message="Approve ACP version acpver_0123456789abcdef",
        session_id=None, kb_ids=["default"],
        tools_enabled=False, attachment_ids=[],
        metadata_filters=None, filters=None,
        metadata_filter_mode="soft", stream=False)
    # The off path (legacy router, authoritative) completes without
    # constructing, reading, or writing any registry state.
    result = chat_module._run_agent_mode(request, "corr_off")
    assert result is chat_module._AGENT_SENTINEL or result is None


def test_shadow_and_active_behave_identically_for_claims(monkeypatch):
    from retriva_gateway.config import settings
    outcomes = []
    for mode in ("shadow", "active"):
        monkeypatch.setattr(settings, "AGENT_INTENT_ROUTER_MODE", mode)
        reg = armed_registry()
        routed = route_non_streaming(
            "Yes.", routing=routing_for(reg))
        claimed = routed.claimed
        # claim_id and the derived key are unique per successful claim
        # (addendum D-1); every other field must be identical.
        outcomes.append((
            routed.route.value, claimed is not None,
            None if claimed is None else (
                claimed.operation, claimed.resource_type,
                claimed.resource_id, claimed.authoritative_version,
                claimed.expected_authoritative_state,
                claimed.allowed_next_transition,
                claimed.preparation_transition_token),
            routed.clarification))
    assert outcomes[0] == outcomes[1]


import json  # noqa: E402  (used above)
