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

"""Process-local, content-free routing metrics (Spec 001 Phase E;
architecture §10).

Thread-safe counters + a bounded numeric latency ring; NO new
dependency, NO external exporter, NO persistence — everything is lost
on restart.

Closed metric families (exact accepted names):
``routing_decision_total{route,source}``,
``deterministic_match_total{intent}``,
``classifier_call_total{provider,outcome}``,
``classifier_failure_total{category}``,
``classifier_latency`` (numeric observations),
``clarification_total{reason}``,
``explicit_intent_rejection_total{operation}``,
``workflow_route_total{family}``,
``rag_route_total``,
``classifier_bypass_total{reason}`` — ``reason`` drawn from the closed
bypass-reason vocabulary defined in spec.md §Classifier bypass reason
codes (this module's ``BYPASS_REASON_VALUES`` is the runtime realization of
that contract): ``streaming``, ``deterministic_terminal``, ``multi_intent``,
``confirmation_path``, ``guard_terminal``, ``consequential_candidate``,
``classifier_disabled``; unknown reasons are rejected fail-closed,
``regional_policy_rejection_total``.

Labels are closed, bounded, low-cardinality, and content-free: an
unknown metric or label value raises at call time (content can never
leak into a label).  The ``provider`` label carries the single closed
value ``"core"`` — the transport provider is Core-owned
deployment-global configuration the Gateway cannot select or observe
per request (Spec 001 §11); the label names the transport boundary,
never a specific vendor.

Mode ``off`` never touches this module (its code paths are outside
the instrumented shadow/active routes — the off path has no runtime
metrics dependency).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple

#: Closed metric names (exact accepted families).
METRIC_NAMES = frozenset({
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
})

#: Closed label names per metric family.
LABEL_NAMES: Dict[str, Tuple[str, ...]] = {
    "routing_decision_total": ("route", "source"),
    "deterministic_match_total": ("intent",),
    "classifier_call_total": ("provider", "outcome"),
    "classifier_failure_total": ("category",),
    "clarification_total": ("reason",),
    "explicit_intent_rejection_total": ("operation",),
    "workflow_route_total": ("family",),
    "rag_route_total": (),
    "classifier_bypass_total": ("reason",),
    "regional_policy_rejection_total": (),
}

#: Closed bypass-reason vocabulary (runtime realization of the contract in
#: spec.md §Classifier bypass reason codes). Every emitted reason must be one
#: of these; unknown values are rejected fail-closed by the metrics API.  The
#: label carries no message content, intent names outside this closed enum,
#: resource/tenant/principal/session/KB identifiers, correlation IDs, raw
#: error data, or classifier/provider output.
BYPASS_REASON_VALUES = frozenset({
    "streaming",
    "deterministic_terminal",
    "multi_intent",
    "confirmation_path",
    "guard_terminal",
    "consequential_candidate",
    "classifier_disabled",
})

#: Bounded latency ring: numeric observations only, no identifiers.
_LATENCY_RING_CAPACITY = 256


class RoutingMetrics:
    """Thread-safe, process-local, content-free counters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], int] = {}
        self._latency: Deque[float] = deque(
            maxlen=_LATENCY_RING_CAPACITY)

    # -- counters ---------------------------------------------------------

    def inc(self, metric: str, **labels: str) -> None:
        """Increment a closed metric with closed labels.  Unknown
        metric names, unknown label names, or unbounded label values
        raise immediately (fail closed — content can never leak)."""
        if metric not in METRIC_NAMES:
            raise ValueError(f"unknown routing metric {metric!r}")
        expected = LABEL_NAMES[metric]
        if set(labels) != set(expected):
            raise ValueError(
                f"metric {metric!r} takes labels {expected}, got "
                f"{sorted(labels)}")
        # E-D2: the classifier_bypass_total reason must be drawn from the
        # closed bypass-reason vocabulary — unknown reasons are rejected
        # fail-closed (content can never leak into a label).
        if metric == "classifier_bypass_total":
            reason = labels.get("reason")
            if reason not in BYPASS_REASON_VALUES:
                raise ValueError(
                    f"classifier_bypass_total reason {reason!r} not in "
                    f"closed vocabulary")
        key = (metric, tuple(sorted(labels.items())))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1

    # -- latency -----------------------------------------------------------

    def observe_latency(self, seconds: float) -> None:
        """Record a numeric latency observation (bounded ring; no
        identifiers; lost on restart)."""
        if not isinstance(seconds, (int, float)):
            return
        with self._lock:
            self._latency.append(float(seconds))

    # -- content-free snapshot ----------------------------------------------

    def reset(self) -> None:
        """Clear all counters and the latency ring in place (test-only)."""
        with self._lock:
            self._counters.clear()
            self._latency.clear()

    def snapshot(self) -> Dict[str, object]:
        """Content-free snapshot: counter series (metric + closed
        labels + integer value) and a numeric latency summary.  No
        message, identifier, content, correlation, or raw confidence
        ever appears."""
        with self._lock:
            series = [
                {"metric": metric,
                 "labels": {name: value for name, value in labels},
                 "value": value}
                for (metric, labels), value in sorted(
                    self._counters.items())]
            latencies = list(self._latency)
        summary = {
            "count": len(latencies),
            "capacity": _LATENCY_RING_CAPACITY,
        }
        if latencies:
            summary["min_s"] = round(min(latencies), 4)
            summary["max_s"] = round(max(latencies), 4)
            summary["mean_s"] = round(
                sum(latencies) / len(latencies), 4)
        return {"counters": series, "classifier_latency": summary,
                "collected_at": time.time()}


#: Process-global instance (mode off never reaches the instrumented
#: code paths).
_METRICS = RoutingMetrics()


def routing_metrics() -> RoutingMetrics:
    """The process-global routing metrics."""
    return _METRICS


def reset_routing_metrics_for_tests() -> RoutingMetrics:
    """Test-only: clear the process-global instance in place (so all
    references observe the empty state)."""
    _METRICS.reset()
    return _METRICS
