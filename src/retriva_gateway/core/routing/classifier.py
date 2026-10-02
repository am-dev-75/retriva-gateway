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

"""Gateway classifier interface (Spec 001 Phase D; architecture §5).

The classifier is UNTRUSTED ADVISORY INPUT.  Core returns classification
only; the Gateway owns application workflow policy.  ``CoreEndpoint-
Classifier`` is the only production adapter: a POST to Core's internal
``/v1/intent/classification`` via the trusted ``CoreClient`` path with
the dedicated service credential, the accepted purpose marker, and the
correlation id.  Fakes are used in all tests.

Classifier output is strictly re-validated against the accepted C2
record (taxonomy) plus semantic consistency, and it can NEVER:
create or modify WorkflowContext; create or modify PendingConfirmation;
claim a confirmation; create or modify ClaimedConfirmationContext;
restore a claimed confirmation; select among confirmations; authorize
a tool; execute a workflow; bypass guards; bypass multi-intent Policy B;
select a provider or model.  The Gateway never selects the classifier
provider or model per request (transport selection is Core's
deployment-global configuration).

No-recursion (architecture §6c): the only permitted flow is Gateway
deterministic eligible ambiguity -> CoreEndpointClassifier -> Core
internal endpoint -> provider-neutral transport -> typed classification
-> Gateway validation and policy.  Maximum classification depth is one;
the classifier path never touches chat, RAG, the agent loop, tools, the
reranker, a visual model, or another routing pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from .taxonomy import Intent, IntentClassification, ReasonCode, Topic

# ---------------------------------------------------------------------------
# Configuration (C7 gateway side; process-global, startup-validated)
# ---------------------------------------------------------------------------

#: Closed fail mode (Spec 001 C7: `clarify` is the only permitted
#: value).
FAIL_MODES = ("clarify",)


@dataclass(frozen=True)
class IntentClassifierConfig:
    """Deployment-global gateway classifier policy settings (C7).  Never
    varying by tenant/principal/user/session/KB/message/metadata/
    classifier-response/model-output/tool-output/workflow state."""

    enabled: bool = False
    min_confidence: float = 0.85
    safe_workflow_min_confidence: float = 0.90
    max_input_chars: int = 2000
    max_context_turns: int = 4
    fail_mode: str = "clarify"

    def validate(self) -> None:
        if self.fail_mode not in FAIL_MODES:
            raise ValueError(
                f"AGENT_INTENT_CLASSIFIER_FAIL_MODE must be one of "
                f"{FAIL_MODES}")
        for name, value in (("min_confidence", self.min_confidence),
                            ("safe_workflow_min_confidence",
                             self.safe_workflow_min_confidence)):
            if not 0.50 <= value <= 1.00:
                raise ValueError(
                    f"AGENT_INTENT_CLASSIFIER_{name.upper()} must be "
                    f"within [0.50, 1.00]")
        if self.safe_workflow_min_confidence < self.min_confidence:
            raise ValueError(
                "AGENT_INTENT_CLASSIFIER_SAFE_WORKFLOW_MIN_CONFIDENCE "
                "must be >= AGENT_INTENT_CLASSIFIER_MIN_CONFIDENCE")
        if self.max_input_chars <= 0:
            raise ValueError("max_input_chars must be positive")
        if self.max_context_turns < 0:
            raise ValueError("max_context_turns must be >= 0")


def classifier_config_from_settings() -> IntentClassifierConfig:
    from retriva_gateway.config import settings
    config = IntentClassifierConfig(
        enabled=bool(settings.AGENT_INTENT_CLASSIFIER_ENABLED),
        min_confidence=float(
            settings.AGENT_INTENT_CLASSIFIER_MIN_CONFIDENCE),
        safe_workflow_min_confidence=float(
            settings.AGENT_INTENT_CLASSIFIER_SAFE_WORKFLOW_MIN_CONFIDENCE),
        max_input_chars=int(
            settings.AGENT_INTENT_CLASSIFIER_MAX_INPUT_CHARS),
        max_context_turns=int(
            settings.AGENT_INTENT_CLASSIFIER_MAX_CONTEXT_TURNS),
        fail_mode=settings.AGENT_INTENT_CLASSIFIER_FAIL_MODE)
    config.validate()
    return config


# ---------------------------------------------------------------------------
# Typed failure categories (architecture-accepted closed set)
# ---------------------------------------------------------------------------

class ClassifierFailure(str, Enum):
    """Closed gateway-side failure categories (content-free)."""

    CLASSIFIER_UNAVAILABLE = "classifier_unavailable"
    INVALID_OUTPUT = "invalid_output"
    REGIONAL_POLICY_REJECTED = "regional_policy_rejected"
    CLASSIFIER_DISABLED = "classifier_disabled"


#: Core typed error code -> gateway failure category (deterministic
#: degradation map; provider-specific free-form errors never reach
#: Gateway policy).
_CORE_ERROR_MAP = {
    "timeout": ClassifierFailure.CLASSIFIER_UNAVAILABLE,
    "transport_failed": ClassifierFailure.CLASSIFIER_UNAVAILABLE,
    "provider_rejected": ClassifierFailure.CLASSIFIER_UNAVAILABLE,
    "provider_rate_limited": ClassifierFailure.CLASSIFIER_UNAVAILABLE,
    "retry_exhausted": ClassifierFailure.CLASSIFIER_UNAVAILABLE,
    "internal_error": ClassifierFailure.CLASSIFIER_UNAVAILABLE,
    "request_too_large": ClassifierFailure.CLASSIFIER_UNAVAILABLE,
    "concurrency_rejected": ClassifierFailure.CLASSIFIER_UNAVAILABLE,
    "rate_limited": ClassifierFailure.CLASSIFIER_UNAVAILABLE,
    "unauthenticated": ClassifierFailure.CLASSIFIER_UNAVAILABLE,
    "forbidden": ClassifierFailure.CLASSIFIER_UNAVAILABLE,
    "cancelled": ClassifierFailure.CLASSIFIER_UNAVAILABLE,
    "malformed_response": ClassifierFailure.INVALID_OUTPUT,
    "response_too_large": ClassifierFailure.INVALID_OUTPUT,
    "invalid_response": ClassifierFailure.INVALID_OUTPUT,
    "unsupported_schema_version": ClassifierFailure.INVALID_OUTPUT,
    "unsupported_prompt_version": ClassifierFailure.INVALID_OUTPUT,
    "regional_policy_rejected":
        ClassifierFailure.REGIONAL_POLICY_REJECTED,
    "recursion_rejected": ClassifierFailure.CLASSIFIER_UNAVAILABLE,
    "classifier_disabled": ClassifierFailure.CLASSIFIER_DISABLED,
    "invalid_request": ClassifierFailure.INVALID_OUTPUT,
}


@dataclass(frozen=True)
class IntentClassificationError(Exception):
    """Typed, content-free classification failure."""

    category: ClassifierFailure

    def __str__(self) -> str:
        return f"intent classification failed: {self.category.value}"


# ---------------------------------------------------------------------------
# Request construction (privacy boundary: Spec 001 §request; C6; §29)
# ---------------------------------------------------------------------------

#: Deterministic closed Italian-marker heuristic (language hint only).
_ITALIAN_MARKERS = re.compile(
    r"\b(?:come|cosa|come\s+si|come\s+funziona|qual\s*'?\s*[eè]|"
    r"perch[eé]|vorrei|posso|devo|fammi|fallo|attiva|approva|analizza|"
    r"revisiona|importa)\b|[àèéìòù]", re.IGNORECASE)


def detect_language(message: str) -> str:
    """Closed deterministic language hint: 'it' when Italian markers
    dominate, else 'en'."""
    return "it" if _ITALIAN_MARKERS.search(message or "") else "en"


def build_classification_request(
        message: str,
        *,
        max_input_chars: int,
        ambiguity_class: str,
        workflow_family_hint: Optional[str],
        workflow_context_present: bool,
        pending_confirmation_present: bool,
        correlation_id: str) -> Dict[str, Any]:
    """The minimal privacy-safe request (Spec 001 §request; §29
    minimization): the normalized truncated CURRENT message, closed
    categorical context, prompt identity, purpose marker, and a trace
    correlation id ONLY — never history, tool results, model messages,
    domain payloads, evidence bodies, file contents, resource IDs,
    tenant/principal/session/KB identifiers, confirmation data,
    transport selection, or arbitrary metadata."""
    normalized = " ".join((message or "").split())
    return {
        "schema_version": "1",
        "prompt_id": "retriva-intent-classification",
        "prompt_version": "1",
        "message": normalized[:max(1, int(max_input_chars))],
        "language": detect_language(normalized),
        "ambiguity_class": ambiguity_class,
        "workflow_family_hint": workflow_family_hint,
        "workflow_context_present": bool(workflow_context_present),
        "pending_confirmation_present":
            bool(pending_confirmation_present),
        "purpose": "intent-classification",
        "correlation_id": correlation_id[:128],
    }


# ---------------------------------------------------------------------------
# Response re-validation (untrusted advisory output; TR42-TR44, A46)
# ---------------------------------------------------------------------------

_INFORMATIONAL_INTENTS = (
    Intent.RAG_QUESTION, Intent.WORKFLOW_DOCUMENTATION,
    Intent.STATUS_EXPLANATION, Intent.CAPABILITY_QUESTION)

_TOPIC_PREFIXES = {
    Topic.ACP: "ACP_",
    Topic.QUALIFICATION: "QUALIFICATION_",
    Topic.COMPANY_IMPORT: "COMPANY_IMPORT_",
    Topic.CAMPAIGN: "CAMPAIGN_",
}


def validate_classification(payload: Any) -> IntentClassification:
    """Strict re-validation of the untrusted C2 payload: schema model
    (extra='forbid', closed enums, strict bounded confidence —
    string/NaN/infinity/out-of-range rejected) plus semantic
    consistency (topic/intent agreement).  Any violation raises
    IntentClassificationError(INVALID_OUTPUT)."""
    if not isinstance(payload, dict):
        raise IntentClassificationError(
            ClassifierFailure.INVALID_OUTPUT)
    try:
        record = IntentClassification.model_validate(payload)
    except Exception:  # noqa: BLE001 — typed category only
        raise IntentClassificationError(
            ClassifierFailure.INVALID_OUTPUT) from None
    # Semantic consistency: a workflow intent must agree with its
    # topic (an ACP_* intent on a CAMPAIGN topic is contradictory);
    # informational intents may sit on any topic.
    prefix = _TOPIC_PREFIXES.get(record.topic)
    if prefix is not None and record.intent.value.startswith(
            ("ACP_", "QUALIFICATION_", "COMPANY_IMPORT_", "CAMPAIGN_")) \
            and not record.intent.value.startswith(prefix):
        raise IntentClassificationError(
            ClassifierFailure.INVALID_OUTPUT)
    if (record.intent is Intent.CLARIFICATION_REQUIRED
            and not record.clarification_reason):
        raise IntentClassificationError(
            ClassifierFailure.INVALID_OUTPUT)
    return record


# ---------------------------------------------------------------------------
# Transport protocol and the single production adapter
# ---------------------------------------------------------------------------

class IntentClassifier:
    """Structural protocol: classify one request to one C2 record or a
    typed error.  ``classify`` accepts no transport override."""

    async def classify(self, request: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class CoreEndpointClassifier(IntentClassifier):
    """The ONLY production adapter: POST to Core's internal
    ``/v1/intent/classification`` through the trusted CoreClient path.

    Carries the dedicated service credential
    (``X-Service-Token``), the accepted purpose marker
    (``X-Retriva-Internal-Purpose: intent-classification``), and the
    correlation id.  The request and response carry no provider, model,
    endpoint, region, or credential fields (transport selection is
    Core's deployment-global configuration; the Gateway cannot select
    it per request).  Recursion guard: this is a dedicated transport —
    it never targets ``/v1/chat/completions`` or any application path.
    """

    def __init__(self, *, service_auth_token: str = "",
                 timeout_seconds: float = 35.0) -> None:
        self._token = service_auth_token
        self._timeout = timeout_seconds

    async def classify(self, request: Dict[str, Any]) -> Dict[str, Any]:
        import httpx
        from retriva_gateway.config import settings
        from retriva_gateway.core.client import core_client
        from retriva_gateway.core.context import get_correlation_id

        token = self._token or (
            settings.AGENT_INTENT_CLASSIFIER_SERVICE_AUTH_TOKEN or "")
        if not token:
            raise IntentClassificationError(
                ClassifierFailure.CLASSIFIER_UNAVAILABLE)
        url = f"{core_client.chat_base_url.rstrip('/')}" \
              f"/v1/intent/classification"
        headers = {
            "X-Service-Token": token,
            "X-Retriva-Internal-Purpose": "intent-classification",
            "X-Correlation-ID": (request.get("correlation_id")
                                 or get_correlation_id() or ""),
            "Content-Type": "application/json",
        }
        import json as _json
        try:
            async with httpx.AsyncClient(
                    timeout=float(self._timeout)) as client:
                response = await client.post(
                    url, content=_json.dumps(request).encode("utf-8"),
                    headers=headers)
        except (httpx.TimeoutException, httpx.TransportError):
            raise IntentClassificationError(
                ClassifierFailure.CLASSIFIER_UNAVAILABLE) from None
        if response.status_code == 401:
            raise IntentClassificationError(
                ClassifierFailure.CLASSIFIER_UNAVAILABLE)
        if response.status_code == 403:
            raise IntentClassificationError(
                ClassifierFailure.CLASSIFIER_UNAVAILABLE)
        if response.status_code >= 400:
            category = ClassifierFailure.CLASSIFIER_UNAVAILABLE
            try:
                code = response.json().get("error", {}).get("code", "")
            except Exception:  # noqa: BLE001
                code = ""
            category = _CORE_ERROR_MAP.get(code, category)
            raise IntentClassificationError(category)
        try:
            return response.json()
        except Exception:  # noqa: BLE001
            raise IntentClassificationError(
                ClassifierFailure.INVALID_OUTPUT) from None
