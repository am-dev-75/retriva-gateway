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

from .deterministic import (
    DeterministicEngine,
    DeterministicResult,
    RULE_PRIORITIES,
    normalize_message,
)
from .guards import CONSEQUENTIAL_INTENTS, evaluate_consequential_guard
from .pipeline import PhaseBChatRoute, route_non_streaming
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
    "DeterministicEngine",
    "DeterministicResult",
    "RULE_PRIORITIES",
    "PhaseBChatRoute",
    "DecisionSource",
    "Explicitness",
    "Intent",
    "IntentClassification",
    "InteractionMode",
    "ReasonCode",
    "Route",
    "RoutingDecision",
    "Topic",
    "evaluate_consequential_guard",
    "normalize_message",
    "route_non_streaming",
]
