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

"""Phase B explicit-intent guard SCAFFOLD (Spec 001; NOT the final guard).

Limitations (by design, per the accepted Phase B authorization):

- this is a scaffold, not the Phase C guard: it validates only what needs
  no workflow state — an explicit operation verb and an explicitly stated
  opaque resource identifier;
- it creates NO confirmation state, holds NO in-memory confirmation
  registry (that is Phase C's typed workflow-context registry), and infers
  nothing from conversation history;
- it authorizes nothing: a PASS merely lets the message ENTER the bounded
  agent loop, where every tool re-validates permission, tenant, ownership,
  lifecycle state, and explicit intent server-side (ADR-0001/0023;
  authorization lives at the tool boundary, never here);
- it calls no model, no provider, no tool, and never fabricates a
  resource.

The Phase C guard will extend PASS conditions with typed workflow-context
hits (same tenant/session/kb, matching resource type, allowed next
operation, unexpired) and typed pending confirmations for bare
affirmatives.  Until then, every consequential request without an explicit
opaque identifier fails closed to clarification.
"""

from dataclasses import dataclass
from typing import FrozenSet, Optional

from .deterministic import DeterministicResult, _OPAQUE_ID
from .taxonomy import Explicitness, Intent, ReasonCode

# The consequential set (Spec 001 §Definitions; every member requires the
# deterministic explicit-intent path — classifier output can never route
# into any of these).
CONSEQUENTIAL_INTENTS: FrozenSet[Intent] = frozenset({
    Intent.ACP_COHORT_APPROVAL,
    Intent.ACP_APPROVAL,
    Intent.ACP_ACTIVATION,
    Intent.ACP_SUPERSESSION,
    Intent.ACP_ROLLBACK,
    # Gate B correction (owner decision D-3): the accepted ACP
    # evidence-enrichment request and the evidence acceptance are
    # consequential per the accepted agent/tools.py ToolDefinitions
    # (destructive=True) and ADR-024 decisions 4/6.
    Intent.ACP_EVIDENCE_ENRICHMENT,
    Intent.ACP_EVIDENCE_ACCEPTANCE,
    Intent.QUALIFICATION_APPROVAL,
    Intent.COMPANY_IMPORT_APPROVAL,
    Intent.COMPANY_IMPORT_COMMIT,
    Intent.CAMPAIGN_AUDIENCE_APPROVAL,
    Intent.CAMPAIGN_AUDIENCE_COMMIT,
    Intent.CAMPAIGN_HISTORY_IMPORT,
    Intent.CAMPAIGN_MARK_ADDRESSED,
    Intent.CAMPAIGN_OUTCOME_UPDATE,
})


@dataclass(frozen=True)
class GuardScaffoldResult:
    """PASS = may enter the bounded agent loop (never authorization)."""

    passed: bool
    reason_codes: FrozenSet[ReasonCode]


def evaluate_consequential_guard(
        result: DeterministicResult,
        *,
        resolved_resource: Optional[str] = None,
) -> GuardScaffoldResult:
    """Fail-closed explicit-intent check for consequential operations.

    PASS requires ALL of:
    1. an explicit operation verb in the current message (the engine's
       EXPLICIT explicitness — negation, hypothetical framing, quotation,
       and code blocks already vetoed upstream);
    2. an explicitly stated opaque resource identifier, OR — Phase C
       only — a resource resolved from the typed WorkflowContext
       registry by the pipeline (``resolved_resource``: trusted server
       routing state; routing assistance only, never authorization).

    Anything else fails closed; the pipeline then clarifies.
    """
    if result.intent not in CONSEQUENTIAL_INTENTS:
        # Safe proposals/analysis need no guard; unavailable vocabulary
        # never reaches the agent loop at all.
        return GuardScaffoldResult(passed=True, reason_codes=frozenset())

    reasons: FrozenSet[ReasonCode] = frozenset()
    if result.explicitness != Explicitness.EXPLICIT:
        reasons = reasons | {ReasonCode.GUARD_RESOURCE_UNRESOLVED}
    resource = result.resource_reference or resolved_resource
    if not resource or not _OPAQUE_ID.fullmatch(resource):
        reasons = reasons | {ReasonCode.GUARD_RESOURCE_UNRESOLVED}
    return GuardScaffoldResult(
        passed=not reasons, reason_codes=reasons)
