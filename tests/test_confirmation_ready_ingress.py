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

"""ConfirmationReadyOutcome Gateway ingress tests (Spec 001 Phase C0 /
ADR-026; TR95-TR107 proof mapping).

The mirrored validator accepts the canonical valid fixture and rejects
every malformed, unknown-version, unknown-field, unknown-enum,
malformed-identifier, out-of-bound, malformed-timestamp, and
correlation/tenant/principal-mismatched block (TR99-TR101, TR100).
The approve tool transports an accepted block verbatim and removes a
rejected one while preserving the completed approval (TR104); nothing
acts on the block and no automatic activation occurs (TR106).  The
sibling test compares the Gateway-local fixture with the CRM-owned
canonical fixture when the sibling checkout exists (TR105) — the
Gateway-local acceptance is the primary proof, so this suite runs
green in isolation.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from retriva_gateway.agent import tools as agent_tools
from retriva_gateway.agent.tools import ToolContext
from retriva_gateway.core.context import Principal, principal_ctx
from retriva_gateway.core.routing.confirmation_ready import (
    ConfirmationReadyBlock,
    ConfirmationReadyRejection,
    RejectionCategory,
    validate_confirmation_ready,
)

FIXTURE = Path(__file__).parent / "fixtures" / (
    "confirmation_ready_v1.json")
CRM_FIXTURE = Path(__file__).resolve().parents[2] / (
    "retriva-crm-assistant/tests/fixtures/"
    "confirmation_ready_outcome_v1.json")

CANONICAL = json.loads(FIXTURE.read_text(encoding="utf-8"))
TRUSTED = {
    "correlation_id": "corr_fixture_0001",
    "tenant_id": "internal-company",
    "principal_id": "user_fixture_01",
}


def validate(payload, **overrides):
    return validate_confirmation_ready(
        payload, **{**TRUSTED, **overrides})


def rejected(payload, **overrides) -> RejectionCategory:
    outcome = validate(payload, **overrides)
    assert isinstance(outcome, ConfirmationReadyRejection), outcome
    return outcome.category


# ---------------------------------------------------------------------------
# Local canonical fixture acceptance (TR99, TR105 primary)
# ---------------------------------------------------------------------------

def test_local_canonical_fixture_is_accepted_verbatim():
    outcome = validate(CANONICAL)
    assert isinstance(outcome, ConfirmationReadyBlock)
    # Transported without rewriting: every authoritative value is
    # preserved field-for-field.
    assert outcome.model_dump() == CANONICAL


def test_accepted_block_is_inert_data_only():
    # The validated model carries no authority, plan, or instruction
    # surface: exactly the closed 17 fields.
    assert set(outcome_fields()) == set(CANONICAL)


def outcome_fields():
    return list(ConfirmationReadyBlock.model_fields)


# ---------------------------------------------------------------------------
# TR101 — unknown schema version / unknown field, version checked first
# ---------------------------------------------------------------------------

def test_unknown_schema_version_rejected_before_other_errors():
    payload = {**CANONICAL, "schema_version": "2", "sneaky": 1}
    assert rejected(payload) is RejectionCategory.UNKNOWN_SCHEMA_VERSION


def test_missing_schema_version_rejected():
    payload = {k: v for k, v in CANONICAL.items()
               if k != "schema_version"}
    assert rejected(payload) is RejectionCategory.UNKNOWN_SCHEMA_VERSION


def test_unknown_field_rejected():
    payload = {**CANONICAL, "arbitrary_metadata": "x"}
    assert rejected(payload) is RejectionCategory.UNKNOWN_FIELD


def test_missing_required_field_rejected_as_malformed_payload():
    payload = {k: v for k, v in CANONICAL.items() if k != "resource_id"}
    assert rejected(payload) is RejectionCategory.MALFORMED_PAYLOAD


def test_non_dict_payload_rejected():
    assert rejected(["not", "a", "dict"]) \
        is RejectionCategory.MALFORMED_PAYLOAD
    assert rejected("block") is RejectionCategory.MALFORMED_PAYLOAD


# ---------------------------------------------------------------------------
# Unknown enum values (TR101)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("discriminator", "acp_version_approved_for_deletion"),
    ("workflow_family", "CAMPAIGN"),
    ("operation", "ACP_DELETION"),
    ("resource_type", "cohort_version"),
    ("expected_authoritative_state", "UNDER_REVIEW"),
    ("allowed_next_transition", "supersede"),
    ("producing_service", "retriva-gateway"),
    ("producing_operation", "activate_acp_version"),
])
def test_unknown_enum_values_rejected(field, value):
    assert rejected({**CANONICAL, field: value}) \
        is RejectionCategory.UNKNOWN_ENUM


# ---------------------------------------------------------------------------
# Malformed identifiers and bounds (TR99)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("token", [
    "ACPAPL_0123456789ABCDEF",
    "acpapl_short",
    "acpapl_0123456789abcdeff",
    "cohort_0123456789abcdef",
    "",
])
def test_malformed_preparation_token_rejected(token):
    assert rejected({**CANONICAL,
                     "preparation_transition_token": token}) \
        is RejectionCategory.MALFORMED_IDENTIFIER


@pytest.mark.parametrize("mutation", [
    {"authoritative_version": 0},
    {"authoritative_version": -1},
    {"authoritative_version": "3"},
    {"confirmation_lifetime_seconds": 0},
    {"confirmation_lifetime_seconds": 901},
    {"confirmation_lifetime_seconds": 300.5},
])
def test_invalid_bounds_rejected(mutation):
    assert rejected({**CANONICAL, **mutation}) \
        is RejectionCategory.INVALID_BOUNDS


@pytest.mark.parametrize("mutation", [
    {"tenant_id": ""},
    {"tenant_id": "x" * 129},
    {"principal_id": ""},
    {"principal_id": "x" * 129},
    {"resource_id": ""},
    {"resource_id": "x" * 129},
    {"correlation_id": ""},
    {"correlation_id": "x" * 129},
])
def test_identifier_shape_defects_rejected(mutation):
    assert rejected({**CANONICAL, **mutation}) \
        is RejectionCategory.MALFORMED_IDENTIFIER


@pytest.mark.parametrize("created_at", [
    "not-a-timestamp",
    "2026-10-01T00:00:00",
    "2026-10-01T00:00:00+02:00",
    "",
])
def test_malformed_timestamp_rejected(created_at):
    assert rejected({**CANONICAL, "created_at": created_at}) \
        is RejectionCategory.MALFORMED_TIMESTAMP


def test_z_suffix_utc_timestamp_accepted():
    outcome = validate({**CANONICAL,
                        "created_at": "2026-10-01T00:00:00Z"})
    assert isinstance(outcome, ConfirmationReadyBlock)


# ---------------------------------------------------------------------------
# TR100 — correlation / tenant / principal cross-checks
# ---------------------------------------------------------------------------

def test_correlation_mismatch_rejected():
    assert rejected(CANONICAL, correlation_id="corr_other_0001") \
        is RejectionCategory.CORRELATION_MISMATCH


def test_missing_trusted_correlation_rejected():
    assert rejected(CANONICAL, correlation_id="") \
        is RejectionCategory.CORRELATION_MISMATCH


def test_tenant_mismatch_rejected():
    assert rejected(CANONICAL, tenant_id="other-tenant") \
        is RejectionCategory.TENANT_MISMATCH


def test_missing_trusted_tenant_rejected():
    assert rejected(CANONICAL, tenant_id="") \
        is RejectionCategory.TENANT_MISMATCH


def test_principal_mismatch_rejected():
    assert rejected(CANONICAL, principal_id="someone_else") \
        is RejectionCategory.PRINCIPAL_MISMATCH


def test_anonymous_trusted_principal_rejected():
    assert rejected(CANONICAL, principal_id="anonymous") \
        is RejectionCategory.PRINCIPAL_MISMATCH


def test_missing_trusted_principal_rejected():
    assert rejected(CANONICAL, principal_id="") \
        is RejectionCategory.PRINCIPAL_MISMATCH


# ---------------------------------------------------------------------------
# TR106 — no storage, no claim API, no authority (structural)
# ---------------------------------------------------------------------------

def test_validator_module_exposes_no_storage_or_claim_api():
    import retriva_gateway.core.routing.confirmation_ready as module
    forbidden = {"store", "save", "claim", "registry", "pending",
                 "consume", "renew", "create_pending",
                 "create_confirmation", "delete", "session"}
    exposed = {name for name in dir(module)
               if not name.startswith("__")}
    assert not (exposed & forbidden)
    # Pure functions: nothing mutable at module level beyond constants
    # and the models themselves.
    for name in ("validate_confirmation_ready",):
        assert callable(getattr(module, name))


def test_routing_package_export_is_validation_only():
    import retriva_gateway.core.routing as routing
    assert routing.ConfirmationReadyBlock is ConfirmationReadyBlock
    assert callable(routing.validate_confirmation_ready)
    assert not hasattr(routing, "PendingConfirmation")
    assert not hasattr(routing, "WorkflowContext")


# ---------------------------------------------------------------------------
# Tool pass-through behavior (TR104, TR106)
# ---------------------------------------------------------------------------

@contextmanager
def principal(pid):
    token = principal_ctx.set(Principal(
        id=pid, name="", email="", roles=["user"], permissions=[]))
    try:
        yield
    finally:
        principal_ctx.reset(token)


def make_ctx():
    return ToolContext(
        session_id="sess_fixture_0001", kb_id="default",
        correlation_id="corr_fixture_0001")


def run_approve_tool(monkeypatch, upstream_approve):
    calls: list = []

    async def fake_acp_call(method, path, json_payload=None):
        calls.append((method, path))
        if method == "GET":
            return {"status": "UNDER_REVIEW"}
        return dict(upstream_approve)

    monkeypatch.setattr(agent_tools, "_acp_call", fake_acp_call)
    with principal("user_fixture_01"):
        result = asyncio.run(agent_tools._tool_approve_acp(
            {"acp_id": "acpver_0123456789abcdef", "version_number": 3},
            make_ctx()))
    return result, calls


def test_tool_result_absent_block_preserves_existing_shape(monkeypatch):
    result, calls = run_approve_tool(monkeypatch, {
        "acp_id": "acpver_0123456789abcdef", "version": 3,
        "status": "APPROVED"})
    assert "confirmation_ready" not in result
    assert result["activation_ready"] is True
    assert result["active_acp_unchanged"] is True
    assert result["acp_id"] == "acpver_0123456789abcdef"
    assert result["version"] == 3


def test_tool_result_valid_block_passes_through_verbatim(monkeypatch):
    result, calls = run_approve_tool(monkeypatch, {
        "acp_id": "acpver_0123456789abcdef", "version": 3,
        "status": "APPROVED",
        "confirmation_ready": dict(CANONICAL)})
    assert result["confirmation_ready"] == CANONICAL
    # Every authoritative value preserved; nothing rewritten.
    assert result["confirmation_ready"]["preparation_transition_token"] \
        == "acpapl_0123456789abcdef"
    # The legacy result fields are unchanged by the presence of the
    # block.
    assert result["activation_ready"] is True
    assert result["active_acp_unchanged"] is True


def test_tool_result_invalid_block_removed_approval_preserved(monkeypatch):
    poisoned = {**CANONICAL, "tenant_id": "not-the-tenant"}
    result, calls = run_approve_tool(monkeypatch, {
        "acp_id": "acpver_0123456789abcdef", "version": 3,
        "status": "APPROVED",
        "confirmation_ready": poisoned})
    assert "confirmation_ready" not in result
    assert result["activation_ready"] is True
    assert result["active_acp_unchanged"] is True
    assert result["acp_id"] == "acpver_0123456789abcdef"
    assert result["status"] == "APPROVED"


def test_no_automatic_activation_from_the_block(monkeypatch):
    result, calls = run_approve_tool(monkeypatch, {
        "acp_id": "acpver_0123456789abcdef", "version": 3,
        "status": "APPROVED",
        "confirmation_ready": dict(CANONICAL)})
    assert result["confirmation_ready"] == CANONICAL
    # Only the read and the approve mutation were performed — never
    # the activation (the block is inert preparation evidence).
    assert all("/activate" not in path for _, path in calls)
    assert any(path.endswith("/approve") for _, path in calls)


# ---------------------------------------------------------------------------
# TR105 — cross-repository canonical contract compatibility (sibling)
# ---------------------------------------------------------------------------

def test_crm_canonical_fixture_accepted_and_identical():
    if not CRM_FIXTURE.exists() or not os.path.isfile(CRM_FIXTURE):
        pytest.skip("Sibling CRM checkout required for the "
                    "cross-repository fixture comparison")
    crm_canonical = json.loads(CRM_FIXTURE.read_text(encoding="utf-8"))
    # The CRM-owned fixture validates against the Gateway mirror.
    outcome = validate(crm_canonical)
    assert isinstance(outcome, ConfirmationReadyBlock)
    # And is semantically identical to the Gateway-local fixture.
    assert outcome.model_dump() == CANONICAL
    assert crm_canonical == CANONICAL
