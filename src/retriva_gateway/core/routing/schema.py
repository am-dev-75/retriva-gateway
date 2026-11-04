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

"""Strict SC2 contract for the catalog-driven semantic router.

Spec 040 Phase B.  The router's output is the closed JSON v2 object
defined by Spec 040 §7.  This module is the Gateway's validator: unknown
fields are rejected, confidence is a strict finite float in [0, 1], the
decision is a closed enum, and the family enum is generated from the
catalog-derived capability cards, so a family that is not in the cards can
never validate.

The contract intentionally contains NO tool, operation, resource,
identifier, authorization, tenant, session, or execution field.  The
router selects a data plane only; the Gateway remains the authority.

Phase B only: nothing in the chat path imports this module yet.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retriva_gateway.core.routing.cards import derive_cards
from retriva_gateway.core.routing.taxonomy import ReasonCode

SCHEMA_VERSION = "2"
PROMPT_VERSION = "2"

#: Bound on the closed reason-code list (same discipline as the C2
#: classifier contract).
MAX_REASON_CODES = 8

#: Strict, bounded confidence: rejects strings, booleans, NaN and
#: infinities (pydantic's ge/le comparisons fail for non-finite values).
_Confidence = Annotated[float, Field(strict=True, ge=0.0, le=1.0)]


class SemanticDecision(str, Enum):
    """Closed data-plane decision (Spec 040 §7)."""

    RAG = "RAG"
    FAMILY = "FAMILY"
    CLARIFY = "CLARIFY"


#: Families are DERIVED from the capability cards, never hand-written.
#: A family absent from the catalog is not a member and cannot validate.
_CARD_FAMILIES = tuple(card.family for card in derive_cards())
FAMILIES = frozenset(_CARD_FAMILIES)
Family = Enum("Family", {family: family for family in _CARD_FAMILIES},
              type=str)


class SemanticRouteDecisionV2(BaseModel):
    """Closed JSON v2 routing decision (Spec 040 contract SC2).

    Cross-field rules:
    - ``FAMILY`` requires a catalog ``family``; ``RAG``/``CLARIFY`` must
      not carry one;
    - ``requires_clarification`` is true exactly for ``CLARIFY``.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2"]
    prompt_version: Literal["2"]
    decision: SemanticDecision
    family: Optional[Family] = None
    confidence: _Confidence
    requires_clarification: bool
    language: Literal["en", "it"]
    reason_codes: List[ReasonCode] = Field(
        default_factory=list, max_length=MAX_REASON_CODES)

    @model_validator(mode="after")
    def _enforce_consistency(self) -> "SemanticRouteDecisionV2":
        if self.decision is SemanticDecision.FAMILY:
            if self.family is None:
                raise ValueError("FAMILY requires a catalog family")
        elif self.family is not None:
            raise ValueError("only FAMILY may carry a family")
        if self.decision is SemanticDecision.CLARIFY:
            if not self.requires_clarification:
                raise ValueError(
                    "CLARIFY requires requires_clarification=true")
        elif self.requires_clarification:
            raise ValueError(
                "requires_clarification is only valid for CLARIFY")
        return self
