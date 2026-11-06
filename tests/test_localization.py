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

"""Localization tests for the closed deterministic message inventory."""

from __future__ import annotations

import pytest

from retriva_gateway.core.routing.clarifications import build_clarification
from retriva_gateway.core.routing.deterministic import DeterministicResult
from retriva_gateway.core.routing.messages import (
    CLARIFY_TEMPLATES,
    detect_language,
    normalize_language,
    router_clarify,
    template,
)
from retriva_gateway.core.routing.taxonomy import (
    Explicitness,
    Intent,
    InteractionMode,
    ReasonCode,
    Topic,
)


def _result(**overrides):
    base = dict(
        rule="R-TEST", topic=Topic.CAMPAIGN, intent=Intent.AMBIGUOUS,
        mode=InteractionMode.INFORMATIONAL,
        explicitness=Explicitness.AMBIGUOUS,
        reason_codes=(ReasonCode.NO_DETERMINISTIC_MATCH,),
        families=(Topic.CAMPAIGN,),
        consequential_operations=(),
    )
    base.update(overrides)
    return DeterministicResult(**base)


def test_detect_language_and_fallback():
    assert detect_language("Esporta le aziende della campagna in Excel") == "it"
    assert detect_language("Export the campaign companies to Excel") == "en"
    assert detect_language("") == "en"
    assert normalize_language("fr") == "en"
    assert normalize_language(None) == "en"
    assert template("fr", "adjacent") == CLARIFY_TEMPLATES["en"]["adjacent"]


@pytest.mark.parametrize("result", [
    _result(reason_codes=(ReasonCode.MULTI_INTENT,),
            families=(Topic.CAMPAIGN, Topic.QUALIFICATION)),
    _result(intent=Intent.UNSUPPORTED, families=(Topic.GENERAL,)),
    _result(unavailable_vocabulary=True, topic=Topic.CAMPAIGN,
            families=(Topic.CAMPAIGN,)),
    _result(intent=Intent.CAMPAIGN_AUDIENCE_APPROVAL,
            consequential_operations=("approve the campaign audience",),
            reason_codes=(ReasonCode.GUARD_RESOURCE_UNRESOLVED,)),
    _result(reason_codes=(ReasonCode.FOLLOWUP_CONTEXT,)),
    _result(families=()),
    _result(families=(Topic.ACP,)),
    _result(families=(Topic.QUALIFICATION,)),
    _result(families=(Topic.COMPANY_IMPORT,)),
    _result(families=(Topic.CAMPAIGN,)),
])
def test_every_clarification_has_an_italian_variant(result):
    en = build_clarification(result, language="en")
    it = build_clarification(result, language="it")
    assert en and it
    assert en != it
    assert build_clarification(result, language="fr") == en


def test_italian_clarifications_use_italian_markers():
    cases = {
        "adjacent": _result(families=()),
        "campaign": _result(families=(Topic.CAMPAIGN,)),
        "multi": _result(reason_codes=(ReasonCode.MULTI_INTENT,),
                         families=(Topic.CAMPAIGN, Topic.QUALIFICATION)),
        "followup": _result(reason_codes=(ReasonCode.FOLLOWUP_CONTEXT,)),
        "unsupported": _result(intent=Intent.UNSUPPORTED,
                              families=(Topic.GENERAL,)),
    }
    for name, result in cases.items():
        text = build_clarification(result, language="it")
        assert any(marker in text.lower() for marker in (
            "non sono sicuro", "vuoi", "questo messaggio",
            "non ho un contesto", "operazione richiesta")), (name, text)


def test_router_templates_are_localized_and_closed():
    en = router_clarify("en")
    it = router_clarify("it")
    assert "read-only Company Intelligence" in en
    assert "sola lettura" in it
    assert "name the campaign" in en
    assert "indica la campagna" in it
    assert router_clarify("fr") == en


def test_action_clarify_states_the_true_reason_and_lists_reads():
    en = router_clarify("en", action=True, family="CAMPAIGN")
    it = router_clarify("it", action=True, family="CAMPAIGN")
    for text, markers in (
        (en, ("not an available read-only capability", "campaign list",
              "addressed stats", "lineage", "history", "Excel export")),
        (it, ("non è una capacità di sola lettura", "elenco campagne",
              "statistiche aziende", "lineage", "storico",
              "esportazione Excel")),
    ):
        for marker in markers:
            assert marker.lower() in text.lower(), (marker, text)
    # The wrong advice must not appear in the action template.
    assert "name the campaign" not in en.lower()
    assert "indica la campagna" not in it.lower()
    # A non-campaign family uses the generic action wording.
    assert "non è una capacità di sola lettura" in router_clarify(
        "it", action=True, family="ACP").lower()


def test_failure_clarify_is_localized():
    assert "No tool was executed" in router_clarify("en", failure=True)
    assert "Nessuno strumento è stato eseguito" in router_clarify(
        "it", failure=True)
