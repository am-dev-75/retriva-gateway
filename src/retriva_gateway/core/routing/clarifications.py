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

"""Closed, localized clarification-template set (Spec 001/040).

Deterministic templates keyed by (family, ambiguity class) and language.
A clarification response NEVER executes a tool and never contains
LLM-generated text.  Placeholders are restricted to closed-vocabulary
values (family names, operation names) — never raw user input.

Languages: ``en`` and ``it``; anything else falls back to English.
Selection stays a pure function of the typed deterministic input plus the
resolved language, so the same input always yields the same text.
"""

from typing import Tuple

from .deterministic import DeterministicResult
from .messages import (
    CLARIFY_TEMPLATES,
    FAMILY_LABELS,
    OPERATION_LABELS,
    normalize_language,
    router_clarify,
)
from .taxonomy import Intent, ReasonCode


def _family_label(language: str, topic) -> str:
    return FAMILY_LABELS[language].get(
        getattr(topic, "value", str(topic)), str(topic))


def _operation_label(language: str, intent: Intent) -> str:
    return OPERATION_LABELS[language].get(
        intent.name,
        "l'operazione richiesta" if language == "it"
        else "perform that operation")


def build_clarification(result: DeterministicResult,
                        extra_reasons: Tuple[ReasonCode, ...] = (),
                        language: str = "en") -> str:
    """Deterministic clarification text for a typed result (closed set).

    Pure function of the typed input; no LLM, no user-content echo.
    ``extra_reasons`` carries pipeline-level guard reasons.
    ``language`` is ``en``/``it``; other values fall back to English.
    """
    lang = normalize_language(language)
    templates = CLARIFY_TEMPLATES[lang]
    reasons = set(result.reason_codes) | set(extra_reasons)
    families = ", ".join(
        _family_label(lang, f) for f in result.families
    ) or _family_label(lang, "GENERAL")

    if ReasonCode.MULTI_INTENT in reasons:
        return templates["multi_intent"].format(families=families)
    if result.intent == Intent.UNSUPPORTED:
        return templates["unsupported"].format(
            operation=_operation_label(lang, result.intent))
    if result.unavailable_vocabulary:
        return templates["unavailable_vocabulary"].format(
            family=_family_label(lang, result.topic))
    if (result.consequential_operations
            and ReasonCode.GUARD_RESOURCE_UNRESOLVED in reasons):
        label = _operation_label(lang, result.intent)
        return templates["consequential_resource"].format(operation=label)
    if ReasonCode.FOLLOWUP_CONTEXT in reasons:
        return templates["followup"]
    if result.families:
        family_key = getattr(result.families[0], "value",
                             str(result.families[0]))
        family_templates = templates["family_ambiguous"]
        if family_key in family_templates:
            return family_templates[family_key]
    return templates["adjacent"]


# Closed template inventory (tested: every template is reachable and the
# set is exactly this tuple) — both languages.
TEMPLATE_INVENTORY: Tuple[str, ...] = tuple(
    value
    for lang in ("en", "it")
    for key, value in CLARIFY_TEMPLATES[lang].items()
    if key != "family_ambiguous"
) + tuple(
    value
    for lang in ("en", "it")
    for value in CLARIFY_TEMPLATES[lang]["family_ambiguous"].values()
)

__all__ = ["build_clarification", "TEMPLATE_INVENTORY", "router_clarify"]
