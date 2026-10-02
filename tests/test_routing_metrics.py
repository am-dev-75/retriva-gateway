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

"""Spec 001 Phase E — metrics tests (core/routing/metrics.py).

Covers: the closed metric-name and label inventory (the 11 families),
rejection of unknown metrics/labels, counter semantics, the bounded
numeric latency ring, the content-free snapshot, and the test reset
helper.  No live endpoint, no side effects on the production singleton
(the tests use the reset helper).
"""

from __future__ import annotations

import pytest

from retriva_gateway.core.routing import (
    LABEL_NAMES,
    METRIC_NAMES,
    reset_routing_metrics_for_tests,
    routing_metrics,
)
from retriva_gateway.core.routing.metrics import BYPASS_REASON_VALUES


EXPECTED_METRICS = {
    "routing_decision_total",
    "deterministic_match_total",
    "classifier_call_total",
    "classifier_failure_total",
    "clarification_total",
    "explicit_intent_rejection_total",
    "workflow_route_total",
    "rag_route_total",
    "classifier_bypass_total",
    "regional_policy_rejection_total",
    # NOTE: classifier_latency is the bounded numeric ring, not a
    # counted family; it is exercised via observe_latency/snapshot.
}


def setup_function(_fn):
    reset_routing_metrics_for_tests()


def _counter(m, metric, **labels):
    for entry in m.snapshot()["counters"]:
        if entry["metric"] == metric and entry["labels"] == labels:
            return entry["value"]
    return 0


def test_metric_names_are_closed_and_complete():
    assert METRIC_NAMES == frozenset(EXPECTED_METRICS)
    # Every metric has a declared (possibly empty) label set.
    for name in METRIC_NAMES:
        assert name in LABEL_NAMES


def test_unknown_metric_is_rejected():
    m = routing_metrics()
    with pytest.raises(ValueError):
        m.inc("not_a_metric")
    # classifier_latency is the numeric ring, not a counted family.
    with pytest.raises(ValueError):
        m.inc("classifier_latency")


def test_unknown_label_is_rejected():
    m = routing_metrics()
    with pytest.raises(ValueError):
        m.inc("routing_decision_total", route="RAG", bogus="x")
    with pytest.raises(ValueError):
        m.inc("classifier_call_total", provider="core",
              outcome="ok", extra="y")


def test_closed_label_names_are_enforced():
    m = routing_metrics()
    # The closed label schema: a known label NAME with a closed value is
    # accepted; an unknown label NAME is rejected (the call sites are
    # responsible for closed values — see chat.py / pipeline.py).
    m.inc("routing_decision_total", route="RAG", source="deterministic")
    assert _counter(m, "routing_decision_total",
                    route="RAG", source="deterministic") == 1
    m.inc("classifier_call_total", provider="core", outcome="ok")
    assert _counter(m, "classifier_call_total",
                    provider="core", outcome="ok") == 1
    # Unknown label NAME is rejected.
    with pytest.raises(ValueError):
        m.inc("routing_decision_total", route="RAG", bogus="x")


def test_counter_semantics_and_reset():
    m = routing_metrics()
    m.inc("rag_route_total")
    m.inc("rag_route_total")
    assert _counter(m, "rag_route_total") == 2
    m.inc("routing_decision_total", route="RAG", source="deterministic")
    m.inc("routing_decision_total", route="RAG", source="deterministic")
    assert _counter(m, "routing_decision_total",
                    route="RAG", source="deterministic") == 2
    assert _counter(m, "routing_decision_total",
                    route="CLARIFY", source="deterministic") == 0
    reset_routing_metrics_for_tests()
    assert _counter(m, "rag_route_total") == 0


def test_latency_ring_is_bounded():
    m = routing_metrics()
    for i in range(500):
        m.observe_latency(0.001 * i)
    snap = m.snapshot()
    lat = snap["classifier_latency"]
    # Bounded ring (cap 256); summary present, no raw records.
    assert lat["count"] == 256
    assert "mean_s" in lat and "min_s" in lat and "max_s" in lat
    assert "raw" not in lat and "samples" not in lat


def test_snapshot_is_content_free():
    m = routing_metrics()
    m.inc("classifier_call_total", provider="core", outcome="ok")
    m.inc("routing_decision_total", route="RAG", source="deterministic")
    snap = m.snapshot()
    blob = str(snap)
    for forbidden in ("token", "secret", "acpver", "Bearer", "message",
                      "prompt", "identifier", "tenant", "principal"):
        assert forbidden not in blob
    assert "counters" in snap and "classifier_latency" in snap


# ---------------------------------------------------------------------------
# Gate E correction (E-D2): classifier_bypass_total carries exactly one closed
# ``reason`` label drawn from a bounded, content-free vocabulary; unknown
# reasons are rejected fail-closed so content can never leak into a label.
# ---------------------------------------------------------------------------

EXPECTED_BYPASS_REASONS = frozenset({
    "mode_off", "streaming", "deterministic_terminal", "multi_intent",
    "confirmation_path", "guard_terminal", "consequential_candidate",
    "classifier_disabled", "classifier_unavailable", "not_eligible",
})


def test_classifier_bypass_reason_label_is_closed():
    # The reason label is declared and bounded.
    assert LABEL_NAMES["classifier_bypass_total"] == ("reason",)
    assert BYPASS_REASON_VALUES == EXPECTED_BYPASS_REASONS


def test_classifier_bypass_total_accepts_closed_reasons():
    m = routing_metrics()
    for reason in BYPASS_REASON_VALUES:
        m.inc("classifier_bypass_total", reason=reason)
        assert _counter(m, "classifier_bypass_total", reason=reason) >= 1


def test_classifier_bypass_total_rejects_unknown_reason():
    m = routing_metrics()
    with pytest.raises(ValueError):
        m.inc("classifier_bypass_total", reason="unknown_reason")


def test_classifier_bypass_total_requires_reason_label():
    # No content-free default — the label is mandatory.
    m = routing_metrics()
    with pytest.raises(ValueError):
        m.inc("classifier_bypass_total")