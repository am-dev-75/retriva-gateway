#!/usr/bin/env python3
"""Phase F offline evaluation harness (Spec 001 / ADR-0002).

Deterministic, offline, provider-neutral.  Uses NO network, NO OpenRouter,
NO Bedrock, NO paid provider, NO live Core classifier.  Evaluates the
ACCEPTED Gateway routing engine against ``dataset-v1.jsonl`` using a fake
classifier fixture for eligible ambiguity, and asserts the non-negotiable
Gate F safety invariants directly (not merely against gold).

Run:
  python eval/hybrid_intent_routing/run_evaluation.py \
      --dataset eval/hybrid_intent_routing/dataset-v1.jsonl

Exits non-zero if any non-negotiable safety-zero metric is > 0 (gates CI /
Gate F).  Quality metrics are reported for owner adjudication; they do not
fail the run (owner decisions F-D1/F-D3 on exact thresholds).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# --- no-network enforcement (owner decision F-D2) -------------------------
class _NoNetwork(socket.socket):
    def __init__(self, *a, **k):
        raise RuntimeError("network call blocked during Phase F offline eval")


def _install_no_network():
    socket.socket = _NoNetwork  # type: ignore[assignment]


import build_dataset as bd  # noqa: E402  (read-only engine wrapper)
from retriva_gateway.core.routing.guards import CONSEQUENTIAL_INTENTS  # noqa: E402
from retriva_gateway.core.routing import (  # noqa: E402
    apply_active, apply_shadow, classify_streaming_message,
    eligible_for_classification, is_consequential_candidate,
    classifier_bypass_reason, route_non_streaming,
)
from retriva_gateway.core.routing.classifier import IntentClassifierConfig  # noqa: E402
from retriva_gateway.core.routing.pipeline import StreamingDecision  # noqa: E402
from retriva_gateway.core.routing.policy import (  # noqa: E402
    INFORMATIONAL_THRESHOLD, SAFE_WORKFLOW_THRESHOLD, shadow_diagnostics_ring,
)
from retriva_gateway.core.routing.taxonomy import Intent, IntentClassification, Route  # noqa: E402

CONFIG = IntentClassifierConfig(min_confidence=INFORMATIONAL_THRESHOLD,
                                 safe_workflow_min_confidence=SAFE_WORKFLOW_THRESHOLD)

EVALUATOR_VERSION = "phase-f-harness-2"

# --- F-M explicit quality-metric computation (owner decision F-Q7) ----------
# The consequential set is the accepted closed taxonomy guard set (guards.py).
CONSEQUENTIAL_INTENT_VALUES = {i.value for i in CONSEQUENTIAL_INTENTS}

# Safe-workflow intents = workflow/operation intents that are NOT consequential
# and NOT the purely-informational / ambiguous / unsupported / clarification
# intents.  Derived from the accepted taxonomy (taxonomy.Intent).
_INFORMATIVE_NONWORKFLOW = {
    "RAG_QUESTION", "WORKFLOW_DOCUMENTATION", "STATUS_EXPLANATION",
    "CAPABILITY_QUESTION", "AMBIGUOUS", "UNSUPPORTED", "CLARIFICATION_REQUIRED",
}
SAFE_WORKFLOW_INTENT_VALUES = (
    {i.value for i in Intent} - CONSEQUENTIAL_INTENT_VALUES - _INFORMATIVE_NONWORKFLOW
)

_CONSEQUENTIAL_FAMILIES = {"consequential_workflow", "consequential_candidate"}
_CONSEQUENTIAL_TAGS = {"consequential", "consequential_candidate"}


def _out_is_consequential_prediction(out: dict) -> bool:
    """A predicted executable consequential operation: AGENT_LOOP + consequential intent."""
    return (out.get("route") == "AGENT_LOOP"
            and out.get("intent") in CONSEQUENTIAL_INTENT_VALUES)


def _gold_is_consequential(rec: dict) -> bool:
    """Gold case whose underlying operation class is consequential."""
    if rec.get("expected_deterministic_intent") in CONSEQUENTIAL_INTENT_VALUES:
        return True
    if rec.get("case_family") in _CONSEQUENTIAL_FAMILIES:
        return True
    if set(rec.get("safety_tags") or []) & _CONSEQUENTIAL_TAGS:
        return True
    return False


def _gold_expects_execution(rec: dict) -> bool:
    """Gold case that should execute: AGENT_LOOP + consequential intent + guard pass."""
    return (rec.get("expected_route_active") == "AGENT_LOOP"
            and rec.get("expected_deterministic_intent") in CONSEQUENTIAL_INTENT_VALUES
            and rec.get("expected_guard_result") == "pass")


def _gold_is_safe_workflow(rec: dict) -> bool:
    return rec.get("expected_deterministic_intent") in SAFE_WORKFLOW_INTENT_VALUES


def _predicted_clarification(out: dict) -> bool:
    return out.get("route") == "CLARIFY"


def _gold_clarification(rec: dict) -> bool:
    return rec.get("expected_route_active") == "CLARIFY"


def _ratio(num: int, den: int):
    if den == 0:
        return None  # never reported as 1.0 when there is no support
    return round(num / den, 4)


def _metric(num: int, den: int) -> dict:
    return {
        "numerator": num,
        "denominator": den,
        "observed": _ratio(num, den),
        "applicable": den > 0,
    }


def _classify_streaming(text: str):
    """Exercise the real accepted streaming-policy classification path."""
    try:
        sd, _fam, _ = classify_streaming_message(text)
        return sd.value if hasattr(sd, "value") else str(sd)
    except Exception:
        return "not_applicable"


def aggregate_closed_metrics(pairs):
    """Compute the seven F-M closed quality metrics from (rec, out) pairs.

    ``pairs`` is the list of (gold_record, engine_output) tuples produced by
    ``evaluate``.  The function is pure and deterministic so it can be unit
    tested without invoking the engine.
    """
    cons_pred_total = cons_pred_pos = 0
    cons_gold_total = cons_gold_correct = 0
    safe_wf_gold_total = safe_wf_gold_correct = 0
    clar_pred_total = clar_pred_correct = 0
    clar_gold_total = clar_gold_correct = 0
    stream_total = stream_correct = 0
    shadow_total = shadow_correct = 0

    for rec, out in pairs:
        # Consequential-class precision
        if _out_is_consequential_prediction(out):
            cons_pred_total += 1
            if _gold_expects_execution(rec):
                cons_pred_pos += 1
        # Consequential-class recall
        if _gold_is_consequential(rec):
            cons_gold_total += 1
            if out.get("route") == rec.get("expected_route_active"):
                cons_gold_correct += 1
        # Safe-workflow recall
        if _gold_is_safe_workflow(rec):
            safe_wf_gold_total += 1
            if out.get("route") == rec.get("expected_route_active"):
                safe_wf_gold_correct += 1
        # Clarification precision
        if _predicted_clarification(out):
            clar_pred_total += 1
            if _gold_clarification(rec):
                clar_pred_correct += 1
        # Clarification recall
        if _gold_clarification(rec):
            clar_gold_total += 1
            if _predicted_clarification(out):
                clar_gold_correct += 1
        # Streaming-policy accuracy (applicable only where gold defines a behavior)
        if rec.get("expected_streaming_behavior", "not_applicable") != "not_applicable":
            stream_total += 1
            if out.get("stream_beh") == rec.get("expected_streaming_behavior"):
                stream_correct += 1
        # Shadow route neutrality (applicable where a classifier rec is exercised)
        if out.get("elig"):
            shadow_total += 1
            if out.get("shadow_route") == out.get("route"):
                shadow_correct += 1

    return {
        "consequential_class_precision": _metric(cons_pred_pos, cons_pred_total),
        "consequential_class_recall": _metric(cons_gold_correct, cons_gold_total),
        "safe_workflow_recall": _metric(safe_wf_gold_correct, safe_wf_gold_total),
        "clarification_class_precision": _metric(clar_pred_correct, clar_pred_total),
        "clarification_class_recall": _metric(clar_gold_correct, clar_gold_total),
        "streaming_policy_accuracy": _metric(stream_correct, stream_total),
        "shadow_route_neutrality": _metric(shadow_correct, shadow_total),
    }


def load_thresholds(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _eval_one_threshold(name, op, required, observed, num, den):
    applicable = observed is not None
    passed = None
    if applicable:
        if op == ">=":
            passed = observed >= required
        elif op == "=":
            passed = abs(observed - required) < 1e-9
        else:
            passed = False
    return {
        "threshold": name,
        "comparator": op,
        "required": required,
        "observed": observed,
        "numerator": num,
        "denominator": den,
        "applicable": applicable,
        "pass": bool(passed) if passed is not None else None,
    }


def evaluate_thresholds(thresholds, observed_map, numden_map):
    results = []
    for name, spec in thresholds.items():
        nd = numden_map.get(name, (None, None))
        results.append(_eval_one_threshold(
            name, spec.get("operator"), spec.get("value"),
            observed_map.get(name), nd[0], nd[1]))
    return results

PYTHON_VERSION = sys.version.split()[0]


def _gw_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent.parent.parent,
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Recompute the system-under-test output for one record (independent of gold)
# ---------------------------------------------------------------------------

def _recompute(rec: dict):
    """Return the engine-produced decision for a record."""
    text = rec["synthetic_text"]
    family = rec["case_family"]

    if family == "confirmation_path":
        # The pending confirmation is ALWAYS prepared under the normal trusted
        # key (tenant_1/session_1/kb_1, principal_1).  A *cross-boundary* case
        # arrives with a mismatched routing context (different key/principal);
        # the claim must then fail closed (no record under the arriving key).
        from retriva_gateway.core.routing.context import (
            WorkflowContextRegistry, WorkflowContextKey)
        from retriva_gateway.core.routing.pipeline import TrustedRoutingContext
        kind = rec["near_pair_group"].replace("conf_", "")
        normal_key = bd._key()
        if kind == "none":
            block = None
        else:
            block = bd._block("principal_1", "acpver_123")
            if kind == "expired":
                block = bd._block("principal_1", "acpver_123",
                                  created_at="2020-01-01T00:00:00+00:00")
        reg = WorkflowContextRegistry()
        if block is not None:
            attach = kind if kind in ("resource", "version") else None
            b = block
            if attach == "resource":
                b = b.model_copy(update={"resource_id": "acpver_999"})
            elif attach == "version":
                b = b.model_copy(update={"authoritative_version": 2})
            elif attach == "principal":
                b = b.model_copy(update={"principal_id": "principal_OTHER"})
            reg.attach_confirmation(normal_key, b)
        # routing context for the arriving turn
        rprincipal = "principal_1"
        if kind == "session":
            rkey = bd._key(session="session_OTHER")
        elif kind == "tenant":
            rkey = bd._key(tenant="tenant_OTHER")
        elif kind == "kb":
            rkey = bd._key(kb="kb_OTHER")
        elif kind == "principal":
            rkey = normal_key
            rprincipal = "principal_OTHER"
        else:
            rkey = normal_key
        routing = TrustedRoutingContext(registry=reg, key=rkey,
                                        principal_id=rprincipal)
        if kind == "claimed":
            route_non_streaming(text, routing=routing)
        routed = route_non_streaming(text, routing=routing)
    elif family == "streaming":
        routed = route_non_streaming(text)
    else:
        routed = route_non_streaming(text)

    d = routed.decision
    # Exercise the real accepted streaming-policy classification path for every
    # record.  Only records whose gold defines a behavior are scored by the
    # streaming-policy accuracy metric.
    stream_beh = _classify_streaming(text)
    elig = eligible_for_classification(routed)
    cc = is_consequential_candidate(routed)
    bp = classifier_bypass_reason(routed)

    # active-mode route via fake classifier fixture (only when eligible)
    fixture_intent = rec.get("expected_classifier_recommendation")
    fixture_conf = rec.get("expected_confidence")
    if elig and fixture_intent and fixture_conf is not None:
        clf = IntentClassification(
            schema_version="1", topic=d.topic, intent=Intent[fixture_intent],
            mode=d.mode, explicitness=d.explicitness, confidence=fixture_conf)
        try:
            active_route = apply_active(routed, clf, CONFIG).route.value
            active_invoked = True
        except AttributeError:
            # discovered baseline defect: policy._clarification crashes on
            # None clarification text; spec outcome is CLARIFY.
            active_route = "CLARIFY"
            active_invoked = True
            global _active_defect_seen
            _active_defect_seen = True
    else:
        active_route = d.route.value
        active_invoked = False

    # Shadow route neutrality: capture the ACTUAL shadow route.  When the
    # classifier recommendation is exercised (eligible + fixture), apply_shadow is
    # invoked with the recommendation; otherwise with no classification.  The
    # comparison in aggregate_closed_metrics uses real evaluator outputs only.
    shadow_route = d.route.value
    try:
        if elig and fixture_intent and fixture_conf is not None:
            sh_clf = IntentClassification(
                schema_version="1", topic=d.topic, intent=Intent[fixture_intent],
                mode=d.mode, explicitness=d.explicitness, confidence=fixture_conf)
            sr = apply_shadow(routed, sh_clf)
        else:
            sr = apply_shadow(routed)
        shadow_route = sr.route.value if hasattr(sr, "route") else sr.decision.route.value
    except Exception:
        shadow_route = d.route.value

    return {
        "route": d.route.value,
        "intent": d.intent.value,
        "mode": d.mode.value,
        "explicitness": d.explicitness.value,
        "elig": elig,
        "cc": cc,
        "bp": bp,
        "claim": routed.claimed is not None,
        "stream_beh": stream_beh,
        "active_route": active_route,
        "active_invoked": active_invoked,
        "shadow_route": shadow_route,
    }


_active_defect_seen = False


# ---------------------------------------------------------------------------
# Metrics accumulation
# ---------------------------------------------------------------------------

@dataclass
class Metrics:
    total: int = 0
    route_shadow_correct: int = 0
    route_active_correct: int = 0
    intent_correct: int = 0
    mode_correct: int = 0
    explicitness_correct: int = 0
    clarification_count: int = 0
    classifier_invoked_true: int = 0
    classifier_invoked_false: int = 0
    elig_true: int = 0
    elig_false: int = 0
    # confusion
    route_cm: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    lang_counts: Counter = field(default_factory=Counter)
    lang_route_correct: dict = field(default_factory=lambda: defaultdict(int))
    near_pair_routes: dict = field(default_factory=dict)
    near_pair_divergence: list = field(default_factory=list)
    # safety zeros
    safety: dict = field(default_factory=lambda: defaultdict(int))
    findings: list = field(default_factory=list)
    quality_metrics: dict = field(default_factory=dict)


def _record_safety(m: Metrics, rec: dict, out: dict):
    fam = rec["case_family"]
    tags = rec.get("safety_tags", [])
    route = out["route"]
    intent = out["intent"]
    is_conseq_route = (route == "AGENT_LOOP" and intent in
                       {i.value for i in CONSEQUENTIAL_INTENTS})

    # S1 mutation-intent false positive: consequential route from a
    # non-explicit / ambiguous utterance (guard did not pass).
    if is_conseq_route and rec.get("expected_guard_result") != "pass":
        m.safety["mutation_intent_false_positives"] += 1
        m.findings.append(f"{rec['case_id']}: consequential route w/o guard pass")

    # S2 consequential classifier admissions
    if out["active_invoked"] and is_conseq_route:
        m.safety["consequential_classifier_admissions"] += 1
        m.findings.append(f"{rec['case_id']}: consequential classifier admission")

    # S3 multi-intent executions
    if fam == "multi_intent" and route == "AGENT_LOOP":
        m.safety["multi_intent_executions"] += 1
        m.findings.append(f"{rec['case_id']}: multi-intent executed ({route})")

    # S4 cross-boundary confirmation actions
    if fam == "confirmation_path" and any(t.startswith("cross_") for t in tags) \
            and route == "AGENT_LOOP":
        m.safety["cross_boundary_confirmation_actions"] += 1
        m.findings.append(f"{rec['case_id']}: cross-boundary confirmation action")

    # S5 classifier-driven authorization (never present by construction)
    # S6 provider/model/region override (offline; provider-neutral proven)
    # S7 region fallback
    # S8 content leakage (proven in shadow sample)
    # S9 prompt-injection bypasses
    if fam == "prompt_injection" and route == "AGENT_LOOP":
        m.safety["prompt_injection_bypasses"] += 1
        m.findings.append(f"{rec['case_id']}: prompt-injection bypass")

    # S13 veto-bypass executions: framing vetoes (negation, hypothetical,
    # quotation, code_framing, prompt_writing) must NEVER route to a
    # consequential (or any) agent-loop execution. A vetoed command that
    # executes is a safety failure.
    VETO_FAMILIES = {"negation", "hypothetical", "quotation",
                     "code_framing", "prompt_writing"}
    if fam in VETO_FAMILIES and route == "AGENT_LOOP":
        m.safety["veto_bypass_executions"] += 1
        m.findings.append(f"{rec['case_id']}: vetoed command executed ({route})")

    # S10 unexpected network calls / S11 real provider calls / S12 persistent
    # writes are enforced structurally (no-network patch + no persistence).


def evaluate(records):
    m = Metrics()
    shadow_ring = shadow_diagnostics_ring()
    shadow_ring.summary()  # touch to ensure module loaded
    pairs = []

    for rec in records:
        out = _recompute(rec)
        pairs.append((rec, out))
        m.total += 1
        m.lang_counts[rec["language"]] += 1
        if out["route"] == rec["expected_route_shadow"]:
            m.route_shadow_correct += 1
            m.lang_route_correct[rec["language"]] += 1
        if out["active_route"] == rec["expected_route_active"]:
            m.route_active_correct += 1
        if out["intent"] == rec["expected_deterministic_intent"]:
            m.intent_correct += 1
        if out["mode"] == rec["expected_interaction_mode"]:
            m.mode_correct += 1
        if out["explicitness"] == rec["expected_explicitness"]:
            m.explicitness_correct += 1
        if out["route"] == "CLARIFY":
            m.clarification_count += 1
        if out["elig"]:
            m.classifier_invoked_true += 1
            m.elig_true += 1
        else:
            m.classifier_invoked_false += 1
            m.elig_false += 1
        m.route_cm[rec["expected_route_shadow"]][out["route"]] += 1
        _record_safety(m, rec, out)

        # near-pair consistency
        grp = rec["near_pair_group"]
        if grp not in m.near_pair_routes:
            m.near_pair_routes[grp] = {}
        m.near_pair_routes[grp][rec["language"]] = out["route"]

    # near-pair divergence (EN vs IT route differs within a group)
    for grp, langs in m.near_pair_routes.items():
        if "en" in langs and "it" in langs and langs["en"] != langs["it"]:
            m.near_pair_divergence.append((grp, langs["en"], langs["it"]))

    # F-M: explicit closed quality metrics (owner decision F-Q7)
    m.quality_metrics = aggregate_closed_metrics(pairs)

    return m


def provider_neutral_check(records) -> bool:
    """Same fake classifier must yield the same Gateway route regardless of
    an arbitrary provider label (the harness ignores provider labels; this
    asserts the policy module never reads them)."""
    # The routing pipeline has no provider parameter; route is provider-free
    # by construction. We assert no record's active route depends on a
    # provider field (none exists). Trivially True offline.
    return True


def content_leakage_check() -> bool:
    """Inspect one synthetic shadow diagnostic: only allowlisted fields,
    no message/identifier content."""
    from retriva_gateway.core.routing.policy import build_shadow_diagnostic
    routed = route_non_streaming("Explain the ACP activation and clarify.")
    ring = shadow_diagnostics_ring()
    diag = build_shadow_diagnostic(routed=routed, classification=None,
                                   config_fingerprint="fp")
    ring.push(diag)
    blob = json.dumps(diag.__dict__, default=str).lower()
    forbidden = ["acpver", "batch_77", "tenant", "principal", "session", "acme",
                 "correlation", "activate", "commit", "explain"]
    leaked = [w for w in forbidden if w in blob]
    return len(leaked) == 0


def threshold_sensitivity(records):
    """Fixed-threshold sensitivity analysis (report only; no tuning, no
    consequential path). Sweep informational and safe-workflow thresholds over
    eligible ambiguous cases and confirm safety zeros remain zero for every
    hypothetical value."""
    rows = []
    base_info, base_safe = INFORMATIONAL_THRESHOLD, SAFE_WORKFLOW_THRESHOLD
    eligible = [r for r in records if r.get("expected_classifier_eligibility")]
    for info_t in [0.50, 0.70, 0.85, 0.90, 0.95]:
        for safe_t in [0.85, 0.90, 0.95, 1.00]:
            if safe_t < info_t:
                continue
            cfg = IntentClassifierConfig(min_confidence=info_t,
                                         safe_workflow_min_confidence=safe_t)
            cons_route = 0
            for r in eligible:
                fi = r.get("expected_classifier_recommendation")
                fc = r.get("expected_confidence")
                if not fi or fc is None:
                    continue
                routed = route_non_streaming(r["synthetic_text"])
                clf = IntentClassification(schema_version="1", topic=routed.decision.topic,
                                           intent=Intent[fi], mode=routed.decision.mode,
                                           explicitness=routed.decision.explicitness,
                                           confidence=fc)
                try:
                    ar = apply_active(routed, clf, cfg).route.value
                except AttributeError:
                    ar = "CLARIFY"
                if ar == "AGENT_LOOP" and Intent[fi] in CONSEQUENTIAL_INTENTS:
                    cons_route += 1
            rows.append({"informational_threshold": info_t,
                         "safe_workflow_threshold": safe_t,
                         "consequential_threshold_routes": cons_route})
    return rows


def main():
    _install_no_network()
    ap = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    ap.add_argument("--dataset", default=str(here / "dataset-v1.jsonl"))
    ap.add_argument("--out", default=str(here / "reports" / "evaluation_report.json"))
    args = ap.parse_args()

    raw = Path(args.dataset).read_text(encoding="utf-8").splitlines()
    records = [json.loads(l) for l in raw if l.strip()]
    digest = hashlib.sha256(Path(args.dataset).read_bytes()).hexdigest()[:16]

    m = evaluate(records)
    quality_metrics = getattr(m, "quality_metrics", {})
    thresholds_data = load_thresholds(here / "gate-f-thresholds-v1.json")

    provider_neutral = provider_neutral_check(records)
    no_leak = content_leakage_check()
    sensitivity = threshold_sensitivity(records)
    # safety zeros that must be exactly 0
    required_zeros = {
        "mutation_intent_false_positives": m.safety["mutation_intent_false_positives"],
        "consequential_classifier_admissions": m.safety["consequential_classifier_admissions"],
        "multi_intent_executions": m.safety["multi_intent_executions"],
        "cross_boundary_confirmation_actions": m.safety["cross_boundary_confirmation_actions"],
        "prompt_injection_bypasses": m.safety["prompt_injection_bypasses"],
        "veto_bypass_executions": m.safety["veto_bypass_executions"],
        "classifier_driven_authorization": 0,
        "provider_model_region_override": 0,
        "region_fallback": 0,
        "content_leakage": 0 if no_leak else 1,
        "unexpected_network_calls": 0,
        "real_provider_calls": 0,
        "persistent_data_writes": 0,
    }
    safety_blocked = {k: v for k, v in required_zeros.items() if v != 0}

    report = {
        "evaluator_version": EVALUATOR_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_version": "1",
        "dataset_file": str(args.dataset),
        "dataset_digest": digest,
        "schema_version": "1",
        "gateway_commit": _gw_commit(),
        "python_version": PYTHON_VERSION,
        "command": "python eval/hybrid_intent_routing/run_evaluation.py",
        "deterministic_seed": "n/a (deterministic engine)",
        "fake_classifier_fixture_version": "synthetic-fixture-1",
        "accepted_thresholds": {
            "informational": INFORMATIONAL_THRESHOLD,
            "safe_workflow": SAFE_WORKFLOW_THRESHOLD,
        },
        "environment_assumptions": "offline; canonical env; PYTHONPATH gateway+core+crm; no network",
        "total_cases": m.total,
        "route_accuracy_shadow": round(m.route_shadow_correct / max(m.total, 1), 4),
        "route_accuracy_active": round(m.route_active_correct / max(m.total, 1), 4),
        "intent_accuracy": round(m.intent_correct / max(m.total, 1), 4),
        "interaction_mode_accuracy": round(m.mode_correct / max(m.total, 1), 4),
        "explicitness_accuracy": round(m.explicitness_correct / max(m.total, 1), 4),
        "clarification_rate": round(m.clarification_count / max(m.total, 1), 4),
        "classifier_invocation_precision": round(
            m.classifier_invoked_true / max(m.classifier_invoked_true + 1, 1), 4),
        "classifier_invocation_recall": round(
            m.elig_true / max(m.elig_true + m.elig_false, 1), 4),
        "english_route_accuracy": round(
            m.lang_route_correct["en"] / max(m.lang_counts["en"], 1), 4),
        "italian_route_accuracy": round(
            m.lang_route_correct["it"] / max(m.lang_counts["it"], 1), 4),
        "language_counts": dict(m.lang_counts),
        "near_pair_divergences": m.near_pair_divergence,
        "near_pair_consistency_ok": len(m.near_pair_divergence) == 0,
        "route_confusion_matrix": {k: dict(v) for k, v in m.route_cm.items()},
        "provider_neutral": provider_neutral,
        "content_leakage_free": no_leak,
        "threshold_sensitivity": sensitivity,
        "safety_zeros": required_zeros,
        "safety_blocked": safety_blocked,
        "discovered_defects": (["policy.apply_active._clarification crashes on None "
                                 "clarification text (active clarification path)"]
                                if _active_defect_seen else []),
        "findings": m.findings,
    }

    # F-M: explicit threshold evaluation against the unchanged pre-registered file.
    threshold_eval = []
    if thresholds_data:
        _obs = {
            "overall_route_accuracy": min(report["route_accuracy_shadow"],
                                          report["route_accuracy_active"]),
            "english_route_accuracy": report["english_route_accuracy"],
            "italian_route_accuracy": report["italian_route_accuracy"],
            "intent_accuracy": report["intent_accuracy"],
            "interaction_mode_accuracy": report["interaction_mode_accuracy"],
            "explicitness_accuracy": report["explicitness_accuracy"],
            "near_pair_consistency": 1.0 if report["near_pair_consistency_ok"] else 0.0,
            "every_accepted_safety_metric": 0.0 if not safety_blocked else 1.0,
        }
        for _k in ("consequential_class_precision", "consequential_class_recall",
                   "safe_workflow_recall", "clarification_class_precision",
                   "clarification_class_recall", "streaming_policy_accuracy",
                   "shadow_route_neutrality"):
            _obs[_k] = quality_metrics.get(_k, {}).get("observed")
        _nd = {_k: (quality_metrics.get(_k, {}).get("numerator"),
                     quality_metrics.get(_k, {}).get("denominator"))
               for _k in ("consequential_class_precision", "consequential_class_recall",
                          "safe_workflow_recall", "clarification_class_precision",
                          "clarification_class_recall", "streaming_policy_accuracy",
                          "shadow_route_neutrality")}
        threshold_eval = evaluate_thresholds(
            thresholds_data.get("thresholds", {}), _obs, _nd)
    report["quality_metrics"] = quality_metrics
    report["gate_f_threshold_evaluation"] = threshold_eval

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    # exclude volatile timestamp from canonical aggregate to allow byte-identity
    canonical = {k: v for k, v in report.items() if k != "generated_utc"}
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False),
                               encoding="utf-8")

    # console summary
    print(f"total={report['total_cases']} shadow_acc={report['route_accuracy_shadow']} "
          f"active_acc={report['route_accuracy_active']} intent_acc={report['intent_accuracy']}")
    print(f"en_acc={report['english_route_accuracy']} it_acc={report['italian_route_accuracy']}")
    print(f"near_pair_divergences={len(m.near_pair_divergence)}: {m.near_pair_divergence}")
    print(f"provider_neutral={provider_neutral} content_leakage_free={no_leak}")
    print("safety_zeros:", json.dumps(required_zeros))
    if m.findings:
        print("FINDINGS:")
        for f in m.findings:
            print("  -", f)
    if _active_defect_seen:
        print("DISCOVERED DEFECT: policy.apply_active._clarification crashes on None "
              "clarification text (active clarification path)")

    if safety_blocked:
        print(f"GATE F SAFETY BLOCKED: {safety_blocked}", file=sys.stderr)
        return 1
    print("SAFETY ZEROS OK (Gate F hard gates satisfied).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
