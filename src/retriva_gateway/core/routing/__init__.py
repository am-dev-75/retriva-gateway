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

"""Hybrid intent routing (Spec 001 / ADR-0002, Phase B).

Phase B contains ONLY the deterministic subset: taxonomy (C1-C3),
deterministic engine, clarification templates, guard scaffold, and the
mode-gated chat integration.  The classifier interface/adapter
(``classifier.py``), workflow-context registry (``context.py``), full
policy (``policy.py``), and metrics (``metrics.py``) arrive in their own
authorized phases (D, C, E, E).
"""

from .confirmation_ready import (
    ConfirmationReadyBlock,
    ConfirmationReadyRejection,
    RejectionCategory,
    validate_confirmation_ready,
)
from .context import (
    AttachOutcome,
    ClaimRejection,
    ClaimResult,
    ClaimedConfirmationContext,
    ConfirmationState,
    PendingConfirmation,
    RegistryStatsSnapshot,
    ResolvedReference,
    WorkflowContext,
    WorkflowContextKey,
    WorkflowContextRegistry,
    derive_execution_idempotency_key,
    from_validated_outcome,
    get_workflow_context_registry,
    observe_tool_result,
    reset_workflow_context_registry_for_tests,
)
from .classifier import (
    ClassifierFailure,
    CoreEndpointClassifier,
    IntentClassificationError,
    IntentClassifierConfig,
    build_classification_request,
    classifier_config_from_settings,
    detect_language,
    validate_classification,
)
from .deterministic import (
    DeterministicEngine,
    DeterministicResult,
    RULE_PRIORITIES,
    is_bare_affirmative_message,
    normalize_message,
)
from .guards import CONSEQUENTIAL_INTENTS, evaluate_consequential_guard
from .policy import (
    ShadowDiagnostic,
    apply_active,
    apply_shadow,
    confidence_bucket,
    confidence_meets,
    shadow_diagnostics_ring,
)
from .metrics import (
    LABEL_NAMES,
    METRIC_NAMES,
    reset_routing_metrics_for_tests,
    routing_metrics,
)
from .pipeline import (
    PhaseBChatRoute,
    StreamingDecision,
    TrustedRoutingContext,
    apply_classification,
    classify_streaming_message,
    classification_context_hints,
    eligible_for_classification,
    is_consequential_candidate,
    classifier_bypass_reason,
    route_non_streaming,
)
from .taxonomy import (
    SCHEMA_VERSION,
    DecisionSource,
    Explicitness,
    Intent,
    IntentClassification,
    InteractionMode,
    ReasonCode,
    Route,
    RoutingDecision,
    Topic,
)

__all__ = [
    "SCHEMA_VERSION",
    "CONSEQUENTIAL_INTENTS",
    "AttachOutcome",
    "ClassifierFailure",
    "ClaimRejection",
    "ClaimResult",
    "ClaimedConfirmationContext",
    "ConfirmationReadyBlock",
    "ConfirmationReadyRejection",
    "ConfirmationState",
    "CoreEndpointClassifier",
    "DeterministicEngine",
    "DeterministicResult",
    "IntentClassificationError",
    "IntentClassifierConfig",
    "PendingConfirmation",
    "RejectionCategory",
    "RegistryStatsSnapshot",
    "ResolvedReference",
    "RULE_PRIORITIES",
    "PhaseBChatRoute",
    "TrustedRoutingContext",
    "WorkflowContext",
    "WorkflowContextKey",
    "WorkflowContextRegistry",
    "DecisionSource",
    "Explicitness",
    "Intent",
    "IntentClassification",
    "IntentClassificationError",
    "IntentClassifierConfig",
    "InteractionMode",
    "LABEL_NAMES",
    "METRIC_NAMES",
    "ReasonCode",
    "Route",
    "RoutingDecision",
    "ShadowDiagnostic",
    "StreamingDecision",
    "Topic",
    "apply_active",
    "apply_classification",
    "apply_shadow",
    "build_classification_request",
    "classifier_config_from_settings",
    "classify_streaming_message",
    "confidence_bucket",
    "confidence_meets",
    "derive_execution_idempotency_key",
    "detect_language",
    "eligible_for_classification",
    "evaluate_consequential_guard",
    "from_validated_outcome",
    "get_workflow_context_registry",
    "is_bare_affirmative_message",
    "is_consequential_candidate",
    "classifier_bypass_reason",
    "normalize_message",
    "observe_tool_result",
    "reset_routing_metrics_for_tests",
    "reset_workflow_context_registry_for_tests",
    "route_non_streaming",
    "routing_metrics",
    "shadow_diagnostics_ring",
    "validate_confirmation_ready",
]
