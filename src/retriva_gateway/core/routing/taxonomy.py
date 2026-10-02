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

"""Closed routing taxonomy and typed contracts (Spec 001 contracts C1-C3).

Phase B of the accepted hybrid-intent-routing spec pack.  These models are
the closed, versioned vocabulary every later phase must reuse unchanged:
adding an enum value or a field requires a specification revision, not an
implementation choice.

Constitutional alignment (Spec 001 §Constitution §11 compatibility):

- no field carries provider, model, endpoint, region, credential, or
  security-policy selection;
- no field carries authorization, tool arguments, routes into tools, or
  execution plans;
- message content influences workflow dispatch only.

C2 note: ``IntentClassification`` is the *classifier output* contract.  The
Phase B deterministic engine never constructs it (no classifier exists until
Phase D); it is defined and validated here so the closed schema is proven by
tests before any classifier transport is authorized.
"""

from enum import Enum
from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# C2/C3 schema version.  Unknown versions are rejected by validation
# (Literal["1"] refuses any other value).
SCHEMA_VERSION = "1"

# Bounded list lengths (closed-schema hygiene; spec C2 "bounded closed list").
_MAX_REASON_CODES = 8
_MAX_CLARIFICATION_REASON_CHARS = 200
_MAX_RESOURCE_REFERENCE_CHARS = 128
_MAX_LANGUAGE_TAG_CHARS = 8


class Topic(str, Enum):
    """C1 topic vocabulary (closed)."""

    ACP = "ACP"
    QUALIFICATION = "QUALIFICATION"
    COMPANY_IMPORT = "COMPANY_IMPORT"
    CAMPAIGN = "CAMPAIGN"
    DOCUMENTATION = "DOCUMENTATION"
    GENERAL = "GENERAL"


class Intent(str, Enum):
    """C1 intent vocabulary (closed, aligned with the accepted tool registry)."""

    RAG_QUESTION = "RAG_QUESTION"
    WORKFLOW_DOCUMENTATION = "WORKFLOW_DOCUMENTATION"
    STATUS_EXPLANATION = "STATUS_EXPLANATION"
    CAPABILITY_QUESTION = "CAPABILITY_QUESTION"
    ACP_COHORT_PROPOSAL = "ACP_COHORT_PROPOSAL"
    ACP_COHORT_REVIEW = "ACP_COHORT_REVIEW"
    ACP_COHORT_APPROVAL = "ACP_COHORT_APPROVAL"
    ACP_GENERATION = "ACP_GENERATION"
    ACP_REVIEW = "ACP_REVIEW"
    ACP_APPROVAL = "ACP_APPROVAL"
    ACP_ACTIVATION = "ACP_ACTIVATION"
    ACP_SUPERSESSION = "ACP_SUPERSESSION"
    ACP_ROLLBACK = "ACP_ROLLBACK"
    ACP_STATUS = "ACP_STATUS"
    ACP_LINEAGE = "ACP_LINEAGE"
    # Gate B correction (owner decision D-3): the accepted ACP
    # evidence-enrichment chat workflows (ADR-024; agent/tools.py).
    ACP_EVIDENCE_ENRICHMENT = "ACP_EVIDENCE_ENRICHMENT"
    ACP_EVIDENCE_ENRICHMENT_STATUS = "ACP_EVIDENCE_ENRICHMENT_STATUS"
    ACP_EVIDENCE_ACCEPTANCE = "ACP_EVIDENCE_ACCEPTANCE"
    QUALIFICATION_REQUEST = "QUALIFICATION_REQUEST"
    QUALIFICATION_STATUS = "QUALIFICATION_STATUS"
    QUALIFICATION_REVIEW = "QUALIFICATION_REVIEW"
    QUALIFICATION_APPROVAL = "QUALIFICATION_APPROVAL"
    COMPANY_IMPORT_ANALYSIS = "COMPANY_IMPORT_ANALYSIS"
    COMPANY_IMPORT_REVIEW = "COMPANY_IMPORT_REVIEW"
    COMPANY_IMPORT_APPROVAL = "COMPANY_IMPORT_APPROVAL"
    COMPANY_IMPORT_COMMIT = "COMPANY_IMPORT_COMMIT"
    COMPANY_IMPORT_STATUS = "COMPANY_IMPORT_STATUS"
    CAMPAIGN_CREATE = "CAMPAIGN_CREATE"
    CAMPAIGN_AUDIENCE_ANALYSIS = "CAMPAIGN_AUDIENCE_ANALYSIS"
    CAMPAIGN_AUDIENCE_REVIEW = "CAMPAIGN_AUDIENCE_REVIEW"
    CAMPAIGN_AUDIENCE_APPROVAL = "CAMPAIGN_AUDIENCE_APPROVAL"
    CAMPAIGN_AUDIENCE_COMMIT = "CAMPAIGN_AUDIENCE_COMMIT"
    CAMPAIGN_HISTORY_IMPORT = "CAMPAIGN_HISTORY_IMPORT"
    CAMPAIGN_MARK_ADDRESSED = "CAMPAIGN_MARK_ADDRESSED"
    CAMPAIGN_OUTCOME_UPDATE = "CAMPAIGN_OUTCOME_UPDATE"
    CAMPAIGN_STATUS = "CAMPAIGN_STATUS"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"


class InteractionMode(str, Enum):
    """C1 interaction-mode vocabulary (closed)."""

    INFORMATIONAL = "INFORMATIONAL"
    ANALYSIS = "ANALYSIS"
    REVIEW = "REVIEW"
    MUTATION = "MUTATION"
    DESTRUCTIVE_MUTATION = "DESTRUCTIVE_MUTATION"
    UNKNOWN = "UNKNOWN"


class Explicitness(str, Enum):
    """C1 explicitness vocabulary (closed)."""

    EXPLICIT = "EXPLICIT"
    IMPLICIT = "IMPLICIT"
    AMBIGUOUS = "AMBIGUOUS"
    NEGATED = "NEGATED"
    HYPOTHETICAL = "HYPOTHETICAL"
    QUOTED_EXAMPLE = "QUOTED_EXAMPLE"


class ReasonCode(str, Enum):
    """Closed reason-code vocabulary for deterministic decisions.

    Phase B emits the deterministic subset; ``FOLLOWUP_CONTEXT`` is emitted
    today for follow-up-shaped turns that lack the (Phase C) typed registry,
    and ``GUARD_RESOURCE_UNRESOLVED`` by the Phase B guard scaffold.
    """

    NO_DETERMINISTIC_MATCH = "NO_DETERMINISTIC_MATCH"
    DOC_FRAMING = "DOC_FRAMING"
    NEGATION = "NEGATION"
    HYPOTHETICAL = "HYPOTHETICAL"
    QUOTED_EXAMPLE = "QUOTED_EXAMPLE"
    CODE_BLOCK = "CODE_BLOCK"
    EXPLICIT_ACTION_VERB = "EXPLICIT_ACTION_VERB"
    CAPABILITY_QUESTION = "CAPABILITY_QUESTION"
    STATUS_QUESTION = "STATUS_QUESTION"
    MULTI_INTENT = "MULTI_INTENT"
    FOLLOWUP_CONTEXT = "FOLLOWUP_CONTEXT"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    WORKFLOW_ADJACENT = "WORKFLOW_ADJACENT"
    NON_ADJACENT_AMBIGUITY = "NON_ADJACENT_AMBIGUITY"
    GUARD_RESOURCE_UNRESOLVED = "GUARD_RESOURCE_UNRESOLVED"
    CONSEQUENTIAL_UNAVAILABLE = "CONSEQUENTIAL_UNAVAILABLE"
    # E-D1 (owner decision E-D1): a recognized consequential operation
    # verb with a missing, generic, unresolved, or invalid resource —
    # the deterministic engine produces an equivalent typed
    # consequential candidate (never classifier-eligible ambiguity).
    CONSEQUENTIAL_CANDIDATE = "CONSEQUENTIAL_CANDIDATE"


class Route(str, Enum):
    """C3 route vocabulary (closed).

    ``REFUSE_STREAM`` is reserved for the Phase E streaming typed error;
    ``LEGACY_RAG`` marks the mode-``off`` legacy route (never constructed by
    the Phase B pipeline — the legacy path in ``chat.py`` is untouched).
    """

    AGENT_LOOP = "AGENT_LOOP"
    RAG = "RAG"
    CLARIFY = "CLARIFY"
    REFUSE_STREAM = "REFUSE_STREAM"
    LEGACY_RAG = "LEGACY_RAG"


class DecisionSource(str, Enum):
    """C3 decision-source vocabulary (closed)."""

    DETERMINISTIC = "deterministic"
    CLASSIFIER = "classifier"
    GUARD = "guard"
    FAIL_CLOSED = "fail_closed"


# Strict, bounded confidence: rejects strings, booleans, NaN and infinities
# (pydantic ge/le comparisons fail for non-finite values; strict=True
# rejects string-typed input outright).
_Confidence = Annotated[float, Field(strict=True, ge=0.0, le=1.0)]


class IntentClassification(BaseModel):
    """C2 — structured classifier contract (schema_version "1").

    The classifier (Phase D) returns this; the Gateway re-validates every
    field and treats the result as an untrusted recommendation.  The closed
    field set intentionally contains NO provider/model/endpoint/region/
    credential/security field, NO authorization field, NO route field, NO
    tool-argument field, and NO execution-plan field (Spec 001 C2, §11).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"]
    topic: Topic
    intent: Intent
    mode: InteractionMode
    explicitness: Explicitness
    confidence: _Confidence
    requires_clarification: bool = False
    clarification_reason: Optional[
        Annotated[str, Field(max_length=_MAX_CLARIFICATION_REASON_CHARS)]
    ] = None
    resource_reference: Optional[
        Annotated[str, Field(max_length=_MAX_RESOURCE_REFERENCE_CHARS)]
    ] = None
    language: Annotated[str, Field(max_length=_MAX_LANGUAGE_TAG_CHARS)] = "en"
    reason_codes: List[ReasonCode] = Field(
        default_factory=list, max_length=_MAX_REASON_CODES)


class RoutingDecision(BaseModel):
    """C3 — route decision record (internal).

    ``confidence`` is classifier-only (``None`` for every deterministic
    decision); ``classifier_invoked`` is False in every Phase B decision
    (no classifier exists until Phase D).
    """

    model_config = ConfigDict(extra="forbid")

    route: Route
    source: DecisionSource
    topic: Topic
    intent: Intent
    mode: InteractionMode
    explicitness: Explicitness
    confidence: Optional[_Confidence] = None
    reason_codes: List[ReasonCode] = Field(
        default_factory=list, max_length=_MAX_REASON_CODES)
    classifier_invoked: bool = False
    shadow: bool = False
