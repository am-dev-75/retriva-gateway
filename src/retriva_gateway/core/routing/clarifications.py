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

"""Closed clarification-template set (Spec 001 Phase B, arch §7).

Deterministic templates keyed by (family, ambiguity class).  A
clarification response NEVER executes a tool and never contains
LLM-generated text.  Placeholders are restricted to closed-vocabulary
values (family names, operation names) — never raw user input, so a
clarification cannot reflect untrusted content as instructions.

Template selection is a pure function of the typed deterministic result:
the same typed input always yields the same text.
"""

from typing import Tuple

from .deterministic import DeterministicResult
from .taxonomy import Intent, ReasonCode, Topic

# Human-readable family labels (closed set, EN only in Phase B — Italian
# clarification localization is recorded as an open question in the Phase B
# closure report, not silently added).
_FAMILY_LABELS = {
    Topic.ACP: "ACP / reference cohorts",
    Topic.QUALIFICATION: "qualification",
    Topic.COMPANY_IMPORT: "company import",
    Topic.CAMPAIGN: "campaigns",
    Topic.DOCUMENTATION: "documentation",
    Topic.GENERAL: "general",
}

_MULTI_INTENT_TEMPLATE = (
    "This message mentions more than one action ({families}). Please send "
    "each action as a separate message; consequential actions require "
    "explicit confirmation."
)

_UNSUPPORTED_TEMPLATE = (
    "That operation ({operation}) is not available from chat: it is not "
    "exposed as a chat workflow. Use the CRM console, or ask me how it "
    "works and I will answer from the documentation."
)

_UNAVAILABLE_VOCABULARY_TEMPLATE = (
    "I recognized a possible {family} request, but this operation is not "
    "available as an explicit chat command yet. Please restate it as a "
    "separate, explicit request (for example with the exact resource "
    "identifier), or ask me how the workflow works."
)

_CONSEQUENTIAL_RESOURCE_TEMPLATE = (
    "To {operation} I need the exact resource identifier (for example an "
    "ACP version id like acpver_…, a qualification job id like job_…, or "
    "an import batch id) and your explicit request. Which resource do you "
    "want to {operation}?"
)

_FOLLOWUP_TEMPLATE = (
    "I don't have an active workflow context for this reply. Please "
    "restate the action you want, including the exact resource (for "
    "example a version or job identifier)."
)

_ADJACENT_TEMPLATE = (
    "I'm not sure whether you want an explanation or a workflow action. "
    "Please restate your request as either a question (for example: 'how "
    "does ACP activation work?') or an explicit command (for example: "
    "'activate ACP version acpver_…')."
)

_FAMILY_AMBIGUOUS_TEMPLATES = {
    Topic.ACP: (
        "Do you want me to explain how ACP generation works, or create a "
        "new PostgreSQL-backed cohort proposal for review?"
    ),
    Topic.QUALIFICATION: (
        "Do you want an explanation of how qualification works, or should "
        "I start a qualification analysis of your candidates?"
    ),
    Topic.COMPANY_IMPORT: (
        "Do you want to know how company imports work, or should I "
        "analyze an import batch for you?"
    ),
    Topic.CAMPAIGN: (
        "Do you want an overview of campaign tracking, or should I analyze "
        "a campaign audience for you?"
    ),
}

# Operation labels for the consequential-resource template (closed set).
_OPERATION_LABELS = {
    Intent.ACP_COHORT_APPROVAL: "approve the cohort proposal",
    Intent.ACP_APPROVAL: "approve the ACP version",
    Intent.ACP_ACTIVATION: "activate the ACP version",
    Intent.ACP_SUPERSESSION: "supersede the active ACP",
    Intent.ACP_ROLLBACK: "roll back the ACP",
    Intent.QUALIFICATION_APPROVAL: "approve the qualification results",
    Intent.COMPANY_IMPORT_APPROVAL: "approve the import batch",
    Intent.COMPANY_IMPORT_COMMIT: "commit the import batch",
    Intent.CAMPAIGN_AUDIENCE_APPROVAL: "approve the campaign audience",
    Intent.CAMPAIGN_AUDIENCE_COMMIT: "commit the campaign audience",
    Intent.CAMPAIGN_HISTORY_IMPORT: "import the campaign history",
    Intent.CAMPAIGN_MARK_ADDRESSED: "mark the campaign audience addressed",
    Intent.CAMPAIGN_OUTCOME_UPDATE: "update the campaign outcome",
}


def _operation_label(intent: Intent) -> str:
    return _OPERATION_LABELS.get(intent, "perform that operation")


def build_clarification(result: DeterministicResult,
                        extra_reasons: Tuple[ReasonCode, ...] = ()) -> str:
    """Deterministic clarification text for a typed result (closed set).

    Pure function of the typed input; no LLM, no user-content echo.
    ``extra_reasons`` carries pipeline-level guard reasons.
    """
    reasons = set(result.reason_codes) | set(extra_reasons)
    families = ", ".join(
        _FAMILY_LABELS.get(f, f.value) for f in result.families
    ) or "general"

    if ReasonCode.MULTI_INTENT in reasons:
        return _MULTI_INTENT_TEMPLATE.format(families=families)
    if result.intent == Intent.UNSUPPORTED:
        return _UNSUPPORTED_TEMPLATE.format(
            operation="requested operation")
    if result.unavailable_vocabulary:
        return _UNAVAILABLE_VOCABULARY_TEMPLATE.format(
            family=_FAMILY_LABELS.get(result.topic, result.topic.value))
    if (result.consequential_operations
            and ReasonCode.GUARD_RESOURCE_UNRESOLVED in reasons):
        label = _operation_label(result.intent)
        return _CONSEQUENTIAL_RESOURCE_TEMPLATE.format(
            operation=label)
    if ReasonCode.FOLLOWUP_CONTEXT in reasons:
        return _FOLLOWUP_TEMPLATE
    if result.families and result.families[0] in _FAMILY_AMBIGUOUS_TEMPLATES:
        return _FAMILY_AMBIGUOUS_TEMPLATES[result.families[0]]
    return _ADJACENT_TEMPLATE


# Closed template inventory (tested: every template is reachable and the
# set is exactly this tuple).
TEMPLATE_INVENTORY: Tuple[str, ...] = (
    _MULTI_INTENT_TEMPLATE,
    _UNSUPPORTED_TEMPLATE,
    _UNAVAILABLE_VOCABULARY_TEMPLATE,
    _CONSEQUENTIAL_RESOURCE_TEMPLATE,
    _FOLLOWUP_TEMPLATE,
    _ADJACENT_TEMPLATE,
) + tuple(_FAMILY_AMBIGUOUS_TEMPLATES.values())
