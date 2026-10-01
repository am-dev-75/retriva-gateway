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

"""Mirrored ConfirmationReadyOutcome ingress validation (Spec 001
Phase C0 / ADR-026; TR95-TR107).

The domain service (retriva-crm-assistant,
``postgres/qualification/confirmation.py``) owns the canonical
contract; this module is the Gateway's strict MIRROR for ingress
validation only.  The Gateway never synthesizes or alters authoritative
fields, never stores the block (Phase C0 has no confirmation storage,
claim API, or registry — TR106), and never interprets the block as
permission to activate: it is preparation evidence only, and the final
activation repeats every domain validation (TR107).

Provenance is established by the transport boundary plus the cross-
checks, not by schema validity alone: the block is accepted only
inside the response to the Gateway-originated service request, with
matching correlation, tenant (the trusted deployment-global
``DEFAULT_TENANT_ID`` — owner decision U-3), and principal (the
authenticated Gateway principal).

Pure functions only: no module-level mutable state, no storage, no
claim API, no mutation authority.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)


# ---------------------------------------------------------------------------
# Contract constants (mirror of ADR-026 §3 — the CRM owns the values)
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1"
_DISCRIMINATOR = "acp_version_approved_for_activation"
_WORKFLOW_FAMILY = "ACP"
_OPERATION = "ACP_ACTIVATION"
_RESOURCE_TYPE = "acp_version"
_EXPECTED_AUTHORITATIVE_STATE = "APPROVED"
_ALLOWED_NEXT_TRANSITION = "activate"
_PRODUCING_SERVICE = "retriva-crm-assistant/acp"
_PRODUCING_OPERATION = "approve_acp_version"

_MAX_ID_LENGTH = 128
_TOKEN_PATTERN = r"^acpapl_[0-9a-f]{16}$"

#: Trusted-principal marker that is never an authorization identity.
_ANONYMOUS_PRINCIPAL = "anonymous"


# ---------------------------------------------------------------------------
# Typed rejection categories (closed)
# ---------------------------------------------------------------------------

class RejectionCategory(str, enum.Enum):
    """Closed rejection categories; content-free (no rejected values)."""

    UNKNOWN_SCHEMA_VERSION = "unknown_schema_version"
    UNKNOWN_FIELD = "unknown_field"
    UNKNOWN_ENUM = "unknown_enum"
    MALFORMED_IDENTIFIER = "malformed_identifier"
    INVALID_BOUNDS = "invalid_bounds"
    MALFORMED_TIMESTAMP = "malformed_timestamp"
    CORRELATION_MISMATCH = "correlation_mismatch"
    TENANT_MISMATCH = "tenant_mismatch"
    PRINCIPAL_MISMATCH = "principal_mismatch"
    MALFORMED_PAYLOAD = "malformed_payload"


class ConfirmationReadyRejection(Exception):
    """Typed, content-free rejection of a confirmation_ready block."""

    def __init__(self, category: RejectionCategory) -> None:
        super().__init__(f"confirmation_ready rejected: "
                         f"{category.value}")
        self.category = category


# ---------------------------------------------------------------------------
# Mirrored strict model (exactly the accepted 17 fields)
# ---------------------------------------------------------------------------

_ENUM_FIELDS = frozenset({
    "schema_version", "discriminator", "workflow_family", "operation",
    "resource_type", "expected_authoritative_state",
    "allowed_next_transition", "producing_service",
    "producing_operation",
})
_IDENTIFIER_FIELDS = frozenset({
    "tenant_id", "principal_id", "resource_id",
    "preparation_transition_token", "correlation_id",
})


class ConfirmationReadyBlock(BaseModel):
    """Strict mirror of the canonical ConfirmationReadyOutcomeBlock.

    Exactly the accepted 17 fields; ``extra="forbid"``; closed
    literals; strict typing (no coercion); opaque identifier formats
    and bounds enforced.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1"] = SCHEMA_VERSION
    discriminator: Literal["acp_version_approved_for_activation"] = \
        _DISCRIMINATOR
    tenant_id: str = Field(min_length=1, max_length=_MAX_ID_LENGTH)
    principal_id: str = Field(min_length=1, max_length=_MAX_ID_LENGTH)
    workflow_family: Literal["ACP"] = _WORKFLOW_FAMILY
    operation: Literal["ACP_ACTIVATION"] = _OPERATION
    resource_type: Literal["acp_version"] = _RESOURCE_TYPE
    resource_id: str = Field(min_length=1, max_length=_MAX_ID_LENGTH)
    authoritative_version: int = Field(gt=0)
    expected_authoritative_state: Literal["APPROVED"] = \
        _EXPECTED_AUTHORITATIVE_STATE
    allowed_next_transition: Literal["activate"] = \
        _ALLOWED_NEXT_TRANSITION
    preparation_transition_token: str = Field(
        min_length=1, max_length=32, pattern=_TOKEN_PATTERN)
    created_at: str = Field(min_length=1, max_length=64)
    confirmation_lifetime_seconds: int = Field(ge=1, le=900)
    correlation_id: str = Field(min_length=1, max_length=_MAX_ID_LENGTH)
    producing_service: Literal["retriva-crm-assistant/acp"] = \
        _PRODUCING_SERVICE
    producing_operation: Literal["approve_acp_version"] = \
        _PRODUCING_OPERATION

    @field_validator("created_at")
    @classmethod
    def _check_created_at(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(
                value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                "created_at must be an RFC 3339 UTC timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(
                "created_at must carry an explicit UTC offset")
        if parsed.utcoffset().total_seconds() != 0:
            raise ValueError("created_at must be normalized to UTC")
        return value


def _categorize(exc: ValidationError) -> ConfirmationReadyRejection:
    """Map a pydantic error to a closed, content-free category."""
    for error in exc.errors():
        error_type = error["type"]
        loc = error["loc"][0] if error["loc"] else None
        if error_type == "extra_forbidden":
            return ConfirmationReadyRejection(
                RejectionCategory.UNKNOWN_FIELD)
        if error_type == "literal_error":
            if loc in _ENUM_FIELDS:
                return ConfirmationReadyRejection(
                    RejectionCategory.UNKNOWN_ENUM)
            return ConfirmationReadyRejection(
                RejectionCategory.MALFORMED_PAYLOAD)
        # Any created_at defect (missing value, bad length, unparsable,
        # naive, non-UTC) is a timestamp defect.
        if loc == "created_at":
            return ConfirmationReadyRejection(
                RejectionCategory.MALFORMED_TIMESTAMP)
        if error_type == "string_pattern_mismatch":
            return ConfirmationReadyRejection(
                RejectionCategory.MALFORMED_IDENTIFIER)
        if error_type in ("string_too_short", "string_too_long",
                          "int_type", "str_type"):
            # Identifier shape defects stay identifier defects; other
            # numeric/length violations are bounds violations.
            if loc in _IDENTIFIER_FIELDS:
                return ConfirmationReadyRejection(
                    RejectionCategory.MALFORMED_IDENTIFIER)
            return ConfirmationReadyRejection(
                RejectionCategory.INVALID_BOUNDS)
        if error_type in ("greater_than", "greater_than_equal",
                          "less_than", "less_than_equal",
                          "int_parsing", "float_type"):
            return ConfirmationReadyRejection(
                RejectionCategory.INVALID_BOUNDS)
        if error_type == "missing":
            return ConfirmationReadyRejection(
                RejectionCategory.MALFORMED_PAYLOAD)
    return ConfirmationReadyRejection(RejectionCategory.MALFORMED_PAYLOAD)


# ---------------------------------------------------------------------------
# Validation + provenance cross-check (pure; TR99-TR101, TR100)
# ---------------------------------------------------------------------------

def validate_confirmation_ready(
        payload: Any,
        *,
        correlation_id: str,
        tenant_id: str,
        principal_id: str,
) -> Union[ConfirmationReadyBlock, ConfirmationReadyRejection]:
    """Strictly validate the block and cross-check trusted provenance.

    ``correlation_id`` is the trusted ToolContext correlation of the
    originating Gateway request; ``tenant_id`` is the trusted
    deployment-global ``DEFAULT_TENANT_ID`` (owner decision U-3);
    ``principal_id`` is the authenticated Gateway principal.  The
    schema version is checked before general model validation, so an
    unknown version never falls through as another category.
    """
    if not isinstance(payload, dict):
        return ConfirmationReadyRejection(
            RejectionCategory.MALFORMED_PAYLOAD)
    if payload.get("schema_version") != SCHEMA_VERSION:
        return ConfirmationReadyRejection(
            RejectionCategory.UNKNOWN_SCHEMA_VERSION)
    try:
        block = ConfirmationReadyBlock.model_validate(payload)
    except ValidationError as exc:
        return _categorize(exc)
    if not (correlation_id or "").strip() \
            or block.correlation_id != correlation_id:
        return ConfirmationReadyRejection(
            RejectionCategory.CORRELATION_MISMATCH)
    if not (tenant_id or "").strip() or block.tenant_id != tenant_id:
        return ConfirmationReadyRejection(
            RejectionCategory.TENANT_MISMATCH)
    principal = (principal_id or "").strip()
    if (not principal or principal == _ANONYMOUS_PRINCIPAL
            or block.principal_id != principal):
        return ConfirmationReadyRejection(
            RejectionCategory.PRINCIPAL_MISMATCH)
    return block
