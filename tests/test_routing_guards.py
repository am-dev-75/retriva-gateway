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

"""Phase B guard scaffold (Spec 001) — fail-closed proof.

The scaffold is NOT the Phase C guard: it validates only explicit verbs
and explicitly stated opaque identifiers, holds no state, creates no
confirmations, and authorizes nothing (PASS only admits a request into
the bounded agent loop, where tools re-validate everything server-side).
"""

import inspect

from retriva_gateway.core.routing import (
    CONSEQUENTIAL_INTENTS,
    DeterministicEngine,
    evaluate_consequential_guard,
)
from retriva_gateway.core.routing.taxonomy import Explicitness, Intent

ENGINE = DeterministicEngine()


def _result(message: str):
    return ENGINE.classify(message)


def test_consequential_intent_set_matches_accepted_operations():
    assert Intent.ACP_COHORT_APPROVAL in CONSEQUENTIAL_INTENTS
    assert Intent.ACP_ACTIVATION in CONSEQUENTIAL_INTENTS
    assert Intent.ACP_SUPERSESSION in CONSEQUENTIAL_INTENTS
    assert Intent.ACP_ROLLBACK in CONSEQUENTIAL_INTENTS
    assert Intent.COMPANY_IMPORT_COMMIT in CONSEQUENTIAL_INTENTS
    assert Intent.CAMPAIGN_MARK_ADDRESSED in CONSEQUENTIAL_INTENTS
    # Safe operations are never in the consequential set.
    assert Intent.ACP_COHORT_PROPOSAL not in CONSEQUENTIAL_INTENTS
    assert Intent.QUALIFICATION_REQUEST not in CONSEQUENTIAL_INTENTS
    assert Intent.AMBIGUOUS not in CONSEQUENTIAL_INTENTS


def test_guard_passes_for_explicit_verb_and_opaque_resource():
    result = _result("Activate ACP version acpver_123.")
    assert result.intent == Intent.ACP_ACTIVATION
    guard = evaluate_consequential_guard(result)
    assert guard.passed is True
    assert not guard.reason_codes


def test_guard_fails_closed_without_explicit_resource():
    result = _result("Activate the ACP")
    guard = evaluate_consequential_guard(result)
    assert guard.passed is False


def test_guard_fails_closed_for_weak_pronoun_references():
    # Pronoun references need the Phase C typed registry.  Phase B
    # clarifies instead of resolving: the pipeline never routes a weak
    # pronoun reference into the agent loop, whatever the inert guard
    # says about the AMBIGUOUS classification.
    from retriva_gateway.core.routing import route_non_streaming
    routed = route_non_streaming("activate it")
    assert routed.route.value == "CLARIFY"
    result = _result("activate it")
    assert result.intent != Intent.ACP_ACTIVATION or \
        evaluate_consequential_guard(result).passed is False


def test_guard_is_inert_for_safe_intents():
    result = _result("Propose a new ACP cohort")
    guard = evaluate_consequential_guard(result)
    assert guard.passed is True  # no consequential check required


def test_guard_is_pure_and_stateless():
    # No state is created or held: identical calls, identical results;
    # the module exposes no mutable registry.
    import retriva_gateway.core.routing.guards as guards_module
    result = _result("Approve ACP version acpver_4.")
    first = evaluate_consequential_guard(result)
    second = evaluate_consequential_guard(result)
    assert first == second
    mutable = {
        name for name, value in vars(guards_module).items()
        if not name.startswith("__")
        and isinstance(value, (dict, list, set))
    }
    assert not mutable, mutable


def test_guard_function_has_no_side_channel_inputs():
    # The scaffold reads only the typed result: no session, tenant,
    # history, or model inputs exist to mis-authorize with.
    signature = inspect.signature(evaluate_consequential_guard)
    assert list(signature.parameters) == ["result"]


def test_guard_cannot_pass_non_explicit_classification():
    # Even a hypothetically non-explicit consequential result must fail.
    result = _result("Activate ACP version acpver_1.")
    object.__setattr__(result, "explicitness", Explicitness.AMBIGUOUS)
    guard = evaluate_consequential_guard(result)
    assert guard.passed is False
