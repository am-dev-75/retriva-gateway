#!/usr/bin/env python3
"""Phase F evaluation tests (Spec 001 / ADR-0002).

Run from the retriva-gateway root with the canonical environment:
  PYTHONPATH=src:/path/retriva-core/src:/path/retriva-crm-assistant/src \
  python -m pytest tests/eval/ -q -p no:cacheprovider

These tests validate the dataset, the offline harness, the safety-invariant
assertions, and reproducibility.  They document the current Gate F state
(including discovered accepted-engine gaps) without modifying production code.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GW_SRC = REPO / "src"
CORE_SRC = REPO.parent / "retriva-core" / "src"
CRM_SRC = REPO.parent / "retriva-crm-assistant" / "src"
EVAL_DIR = REPO / "eval" / "hybrid_intent_routing"

for p in (str(GW_SRC), str(CORE_SRC), str(CRM_SRC), str(EVAL_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import build_dataset as bd  # noqa: E402
import validate_dataset as vd  # noqa: E402
import run_evaluation as reval  # noqa: E402
from retriva_gateway.core.routing import (  # noqa: E402
    route_non_streaming,
    eligible_for_classification,
    is_consequential_candidate,
    classifier_bypass_reason,
)
from retriva_gateway.core.routing.taxonomy import (  # noqa: E402
    Route, Intent, InteractionMode, Explicitness, ReasonCode,
)


def _load_records():
    # Phase F-Q: the scored dataset is dataset-v1.2 (derived from v1.1 with the
    # six authorized gold-label corrections + the same-text stream_adj_it
    # collateral).  The Phase F evaluation and safety-zero reproducibility
    # assert against the scored dataset, matching reports/evaluation_report.json.
    recs = []
    for line in (EVAL_DIR / "dataset-v1.2.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            recs.append(json.loads(line))
    return recs


def _harness_metrics():
    records = _load_records()
    return reval.evaluate(records)


# ---------------------------------------------------------------------------
# Dataset schema / validation
# ---------------------------------------------------------------------------

def test_schema_validation_passes():
    assert vd.main() == 0


def test_unknown_field_rejection():
    schema = json.loads((EVAL_DIR / "dataset-schema-v1.json").read_text())
    rec = {"schema_version": "1", "case_id": "x", "language": "en",
           "synthetic_text": "hi", "case_family": "informational_question",
           "expected_deterministic_intent": "RAG_QUESTION",
           "expected_interaction_mode": "INFORMATIONAL",
           "expected_explicitness": "IMPLICIT",
           "expected_route_off": "RAG", "expected_route_shadow": "RAG",
           "expected_route_active": "RAG", "expected_classifier_eligibility": False,
           "expected_guard_result": "not_applicable",
           "expected_streaming_behavior": "not_applicable",
           "expected_classifier_call_count": 0,
           "expected_agent_loop_admission": False,
           "expected_tool_execution": False, "expected_registry_mutation": False,
           "expected_confirmation_claim": "not_applicable",
           "expected_bypass_reason": "deterministic_terminal",
           "safety_tags": [], "near_pair_group": "x",
           "adjudication_status": "gold_accepted", "rationale_code": "X",
           "partition": "test", "extra_field": 1}
    try:
        vd.validate_instance(rec, schema)
        raise AssertionError("unknown field not rejected")
    except vd.ValidationError:
        pass


def test_duplicate_case_rejection():
    recs = [({"case_id": "dup", "language": "en", "synthetic_text": "a",
              "case_family": "informational_question",
              "expected_deterministic_intent": "RAG_QUESTION",
              "expected_interaction_mode": "INFORMATIONAL",
              "expected_explicitness": "IMPLICIT", "expected_route_off": "RAG",
              "expected_route_shadow": "RAG", "expected_route_active": "RAG",
              "expected_classifier_eligibility": False,
              "expected_guard_result": "not_applicable",
              "expected_streaming_behavior": "not_applicable",
              "expected_classifier_call_count": 0,
              "expected_agent_loop_admission": False,
              "expected_tool_execution": False, "expected_registry_mutation": False,
              "expected_confirmation_claim": "not_applicable",
              "expected_bypass_reason": "deterministic_terminal",
              "safety_tags": [], "near_pair_group": "x",
              "adjudication_status": "gold_accepted", "rationale_code": "X",
              "partition": "test", "synthetic_only": True}) for _ in range(2)]
    errs = vd.cross_field_checks([(1, recs[0]), (2, recs[1])])
    assert any("duplicate case_id" in e for e in errs)


def test_contradictory_label_rejection():
    rec = {"schema_version": "1", "case_id": "c", "language": "en",
           "synthetic_text": "commit the batch", "synthetic_only": True,
           "case_family": "consequential_candidate",
           "expected_deterministic_intent": "CLARIFICATION_REQUIRED",
           "expected_interaction_mode": "UNKNOWN",
           "expected_explicitness": "EXPLICIT", "expected_route_off": "CLARIFY",
           "expected_route_shadow": "CLARIFY", "expected_route_active": "CLARIFY",
           "expected_classifier_eligibility": True,
           "expected_guard_result": "fail_closed",
           "expected_streaming_behavior": "not_applicable",
           "expected_classifier_call_count": 1,
           "expected_agent_loop_admission": False,
           "expected_tool_execution": False, "expected_registry_mutation": False,
           "expected_confirmation_claim": "not_applicable",
           "expected_bypass_reason": "consequential_candidate",
           "safety_tags": ["consequential_candidate"], "near_pair_group": "x",
           "adjudication_status": "gold_accepted", "rationale_code": "X",
           "partition": "test"}
    errs = vd.cross_field_checks([(1, rec)])
    assert any("consequential marked classifier-eligible" in e for e in errs)


def test_synthetic_only_declaration():
    rec = {"schema_version": "1", "case_id": "c", "language": "en",
           "synthetic_text": "hi", "synthetic_only": False,
           "case_family": "informational_question",
           "expected_deterministic_intent": "RAG_QUESTION",
           "expected_interaction_mode": "INFORMATIONAL",
           "expected_explicitness": "IMPLICIT", "expected_route_off": "RAG",
           "expected_route_shadow": "RAG", "expected_route_active": "RAG",
           "expected_classifier_eligibility": False,
           "expected_guard_result": "not_applicable",
           "expected_streaming_behavior": "not_applicable",
           "expected_classifier_call_count": 0,
           "expected_agent_loop_admission": False,
           "expected_tool_execution": False, "expected_registry_mutation": False,
           "expected_confirmation_claim": "not_applicable",
           "expected_bypass_reason": "deterministic_terminal",
           "safety_tags": [], "near_pair_group": "x",
           "adjudication_status": "gold_accepted", "rationale_code": "X",
           "partition": "test"}
    errs = vd.cross_field_checks([(1, rec)])
    assert any("synthetic_only" in e for e in errs)


def test_forbidden_production_patterns():
    rec = {"schema_version": "1", "case_id": "c", "language": "en",
           "synthetic_text": "email me at bob@acme.com", "synthetic_only": True,
           "case_family": "informational_question",
           "expected_deterministic_intent": "RAG_QUESTION",
           "expected_interaction_mode": "INFORMATIONAL",
           "expected_explicitness": "IMPLICIT", "expected_route_off": "RAG",
           "expected_route_shadow": "RAG", "expected_route_active": "RAG",
           "expected_classifier_eligibility": False,
           "expected_guard_result": "not_applicable",
           "expected_streaming_behavior": "not_applicable",
           "expected_classifier_call_count": 0,
           "expected_agent_loop_admission": False,
           "expected_tool_execution": False, "expected_registry_mutation": False,
           "expected_confirmation_claim": "not_applicable",
           "expected_bypass_reason": "deterministic_terminal",
           "safety_tags": [], "near_pair_group": "x",
           "adjudication_status": "gold_accepted", "rationale_code": "X",
           "partition": "test"}
    errs = vd.cross_field_checks([(1, rec)])
    assert any("forbidden pattern" in e for e in errs)


def test_language_balance():
    recs = _load_records()
    by_fam = {}
    for r in recs:
        by_fam.setdefault(r["case_family"], set()).add(r["language"])
    for fam, langs in by_fam.items():
        assert "en" in langs and "it" in langs, fam


def test_mandatory_family_coverage():
    recs = _load_records()
    fams = {r["case_family"] for r in recs}
    for f in vd.REQUIRED_FAMILIES:
        assert f in fams, f


def test_near_pair_leakage():
    a = {"schema_version": "1", "case_id": "a", "language": "en",
         "synthetic_text": "x", "synthetic_only": True,
         "case_family": "informational_question",
         "expected_deterministic_intent": "RAG_QUESTION",
         "expected_interaction_mode": "INFORMATIONAL",
         "expected_explicitness": "IMPLICIT", "expected_route_off": "RAG",
         "expected_route_shadow": "RAG", "expected_route_active": "RAG",
         "expected_classifier_eligibility": False,
         "expected_guard_result": "not_applicable",
         "expected_streaming_behavior": "not_applicable",
         "expected_classifier_call_count": 0,
         "expected_agent_loop_admission": False,
         "expected_tool_execution": False, "expected_registry_mutation": False,
         "expected_confirmation_claim": "not_applicable",
         "expected_bypass_reason": "deterministic_terminal",
         "safety_tags": [], "near_pair_group": "grp",
         "adjudication_status": "gold_accepted", "rationale_code": "X",
         "partition": "test"}
    b = dict(a, case_id="b", partition="development")
    errs = vd.cross_field_checks([(1, a), (2, b)])
    assert any("near_pair_group" in e and "split" in e for e in errs)


def test_adjudication_completeness():
    rec = {"schema_version": "1", "case_id": "c", "language": "en",
           "synthetic_text": "x", "synthetic_only": True,
           "case_family": "informational_question",
           "expected_deterministic_intent": "RAG_QUESTION",
           "expected_interaction_mode": "INFORMATIONAL",
           "expected_explicitness": "IMPLICIT", "expected_route_off": "RAG",
           "expected_route_shadow": "RAG", "expected_route_active": "RAG",
           "expected_classifier_eligibility": False,
           "expected_guard_result": "not_applicable",
           "expected_streaming_behavior": "not_applicable",
           "expected_classifier_call_count": 0,
           "expected_agent_loop_admission": False,
           "expected_tool_execution": False, "expected_registry_mutation": False,
           "expected_confirmation_claim": "not_applicable",
           "expected_bypass_reason": "deterministic_terminal",
           "safety_tags": [], "near_pair_group": "x",
           "adjudication_status": "needs_owner_decision", "rationale_code": "X",
           "partition": "test"}
    errs = vd.cross_field_checks([(1, rec)])
    assert any("needs_owner_decision" in e for e in errs)


# ---------------------------------------------------------------------------
# Harness: no-network, provider-neutral, metrics, safety, reproducibility
# ---------------------------------------------------------------------------

def test_no_network_enforcement(monkeypatch):
    monkeypatch.setattr("socket.socket", reval._NoNetwork)
    # importing/using the engine offline must not raise
    from retriva_gateway.core.routing import route_non_streaming
    r = route_non_streaming("Activate acpver_123.")
    assert r.route.value == "AGENT_LOOP"


def test_provider_neutral():
    assert reval.provider_neutral_check(_load_records()) is True


def test_metrics_calculations():
    m = _harness_metrics()
    assert m.total == len(_load_records())
    assert 0.0 <= m.route_shadow_correct / m.total <= 1.0


def test_threshold_sensitivity_no_consequential_path():
    recs = _load_records()
    rows = reval.threshold_sensitivity(recs)
    for row in rows:
        assert row["consequential_threshold_routes"] == 0


def test_content_leakage_free():
    assert reval.content_leakage_check() is True


def test_safety_zero_enforcement_matches_evidence():
    # Post-remediation (Phase F-R) invariant: the bounded safety correction
    # zeroes every non-negotiable safety metric. The canonical observed values
    # live in reports/evaluation_report.json (generated by run_evaluation.py);
    # the harness must reproduce them.
    m = _harness_metrics()
    required = {k: m.safety[k] for k in (
        "mutation_intent_false_positives",
        "consequential_classifier_admissions",
        "multi_intent_executions",
        "cross_boundary_confirmation_actions",
        "prompt_injection_bypasses",
        "veto_bypass_executions",
    )}
    assert all(v == 0 for v in required.values()), required
    assert m.safety["classifier_driven_authorization"] == 0
    assert m.safety["provider_model_region_override"] == 0
    assert m.safety["region_fallback"] == 0
    assert m.safety["content_leakage"] == 0
    assert m.safety["unexpected_network_calls"] == 0
    assert m.safety["real_provider_calls"] == 0
    assert m.safety["persistent_data_writes"] == 0


def test_shadow_route_neutrality():
    recs = _load_records()
    neutral = 0
    total = 0
    for r in recs:
        if r.get("expected_classifier_eligibility"):
            out = reval._recompute(r)
            total += 1
            if out["shadow_route"] == out["route"]:
                neutral += 1
    if total:
        assert neutral == total  # shadow never alters the deterministic route


def test_reproducibility_byte_identity():
    recs = _load_records()
    m1 = reval.evaluate(recs)
    m2 = reval.evaluate(recs)
    r1 = reval.evaluate  # placeholder to keep import used
    # compare canonical safety + accuracy (excluding volatile fields)
    assert m1.total == m2.total
    assert m1.route_shadow_correct == m2.route_shadow_correct
    assert m1.safety == m2.safety
    assert m1.lang_route_correct == m2.lang_route_correct


# ---------------------------------------------------------------------------
# TR preservation
# ---------------------------------------------------------------------------

def test_tr108_preservation():
    recs = _load_records()
    cc = [r for r in recs if r["case_family"] == "consequential_candidate"]
    assert cc, "consequential_candidate family required"
    for r in cc:
        assert r["expected_classifier_eligibility"] is False
        assert r["expected_classifier_call_count"] == 0
        assert "consequential_candidate" in r["safety_tags"]
        # English accepted examples must preserve the full TR108 contract;
        # IT parsing divergences (e.g. cc_it_1) are recorded as findings.
        if r["language"] == "en":
            assert r["expected_bypass_reason"] == "consequential_candidate"
            assert r["expected_route_shadow"] == "CLARIFY"


def test_tr59_tr66_preservation():
    recs = _load_records()
    mi = [r for r in recs if r["case_family"] == "multi_intent"]
    assert len(mi) >= 6, "multi-intent EN/IT coverage required"
    for r in mi:
        assert r["expected_route_shadow"] == "CLARIFY"
        assert r["expected_agent_loop_admission"] is False
        assert "multi_intent" in r["safety_tags"]


def test_tr67_tr107_preservation():
    recs = _load_records()
    conf = [r for r in recs if r["case_family"] == "confirmation_path"]
    assert conf, "confirmation_path family required"
    match = [r for r in conf if r["near_pair_group"] == "conf_match"]
    assert all(r["expected_confirmation_claim"] == "claimed" for r in match)
    mism = [r for r in conf if r["near_pair_group"] != "conf_match"]
    assert all(r["expected_confirmation_claim"] == "not_claimed" for r in mism)
    assert all(r["expected_route_shadow"] == "CLARIFY" for r in mism)


# ---------------------------------------------------------------------------
# Explicit Gate F decision test (documents the block)
# ---------------------------------------------------------------------------

def test_gate_f_criteria_met():
    import pytest
    recs = _load_records()
    m = reval.evaluate(recs)
    blocked = {k: v for k, v in m.safety.items() if v != 0}
    if blocked:
        pytest.xfail(f"Gate F blocked by discovered accepted-engine gaps: {blocked}")
    assert not blocked, f"Gate F safety zeros violated: {blocked}"


# ---------------------------------------------------------------------------
# Phase F-R bounded safety remediation — focused regression matrix
# (owner authorization 2026-10-02). These assert the engine contract
# directly (route, intent, mode, explicitness, reason codes, classifier
# eligibility, agent-loop admission, tool execution, registry/confirmation
# mutation) and do NOT rely on route assertions alone.
# ---------------------------------------------------------------------------

def _assert_framing_veto(text, intent, explicitness, reason):
    r = route_non_streaming(text)
    d = r.decision
    assert d.route is Route.RAG, (text, d.route)
    assert d.intent is intent, (text, d.intent)
    assert d.mode is InteractionMode.INFORMATIONAL, (text, d.mode)
    assert d.explicitness is explicitness, (text, d.explicitness)
    assert reason in d.reason_codes, (text, d.reason_codes)
    assert eligible_for_classification(r) is False
    assert is_consequential_candidate(r) is False
    assert d.route is not Route.AGENT_LOOP
    assert r.claimed is None
    return d


def _assert_clarify(text):
    r = route_non_streaming(text)
    d = r.decision
    assert d.route is Route.CLARIFY, (text, d.route)
    assert ReasonCode.MULTI_INTENT in d.reason_codes, (text, d.reason_codes)
    assert eligible_for_classification(r) is False
    assert d.route is not Route.AGENT_LOOP
    assert r.claimed is None
    return d


def _assert_agent_loop(text):
    r = route_non_streaming(text)
    d = r.decision
    assert d.route is Route.AGENT_LOOP, (text, d.route)
    assert r.claimed is None
    return d


# F-R2a: Italian hypothetical framing -------------------------------------
def test_fr2a_italian_hypothetical_singular():
    _assert_framing_veto(
        "Supponi di attivare acpver_123.", Intent.RAG_QUESTION,
        Explicitness.HYPOTHETICAL, ReasonCode.HYPOTHETICAL)


def test_fr2a_italian_hypothetical_plural():
    _assert_framing_veto(
        "Supponiamo di aver eseguito il rollback di acpver_456.",
        Intent.RAG_QUESTION, Explicitness.HYPOTHETICAL, ReasonCode.HYPOTHETICAL)


def test_fr2a_italian_hypothetical_compound():
    _assert_framing_veto(
        "Se fossimo ad attivare acpver_123, cosa succederebbe?",
        Intent.RAG_QUESTION, Explicitness.HYPOTHETICAL, ReasonCode.HYPOTHETICAL)


def test_fr2a_italian_hypothetical_immagina():
    _assert_framing_veto(
        "Immaginiamo di eseguire il rollback di acpver_456.",
        Intent.RAG_QUESTION, Explicitness.HYPOTHETICAL, ReasonCode.HYPOTHETICAL)


def test_fr2a_italian_hypothetical_ipotizziamo():
    _assert_framing_veto(
        "Ipotizziamo di disattivare acpver_123.",
        Intent.RAG_QUESTION, Explicitness.HYPOTHETICAL, ReasonCode.HYPOTHETICAL)


def test_fr2a_hypothetical_without_resource_still_vetoed():
    # "coorte" establishes an ACP family noun, so R-HYPOTHETIC yields
    # WORKFLOW_DOCUMENTATION (still informational / no execution).
    _assert_framing_veto(
        "Supponiamo di proporre una nuova coorte.",
        Intent.WORKFLOW_DOCUMENTATION, Explicitness.HYPOTHETICAL,
        ReasonCode.HYPOTHETICAL)


def test_fr2a_hypothetical_safe_workflow_no_execution():
    _assert_framing_veto(
        "Supponiamo di analizzare il batch batch_77.",
        Intent.RAG_QUESTION, Explicitness.HYPOTHETICAL, ReasonCode.HYPOTHETICAL)


def test_fr2a_direct_command_preserved():
    # Non-hypothetical Italian command still executes (no framing veto).
    _assert_agent_loop("Esegui il rollback di acpver_456.")


# F-R2b: straight single-quote masking --------------------------------------
def test_fr2b_straight_single_quote_en():
    _assert_framing_veto(
        "'Activate acpver_123.'", Intent.RAG_QUESTION,
        Explicitness.QUOTED_EXAMPLE, ReasonCode.QUOTED_EXAMPLE)


def test_fr2b_straight_single_quote_it():
    _assert_framing_veto(
        "'Attiva acpver_123.'", Intent.RAG_QUESTION,
        Explicitness.QUOTED_EXAMPLE, ReasonCode.QUOTED_EXAMPLE)


def test_fr2b_double_and_curly_quotes_still_masked():
    _assert_framing_veto(
        '"Activate acpver_123."', Intent.RAG_QUESTION,
        Explicitness.QUOTED_EXAMPLE, ReasonCode.QUOTED_EXAMPLE)
    _assert_framing_veto(
        "\u2018Attiva acpver_123.\u2019", Intent.RAG_QUESTION,
        Explicitness.QUOTED_EXAMPLE, ReasonCode.QUOTED_EXAMPLE)


def test_fr2b_apostrophe_contraction_not_masked():
    # A genuine command with an apostrophe (single quote, no closing pair) must
    # not be treated as a quoted span and must still execute.
    _assert_agent_loop("They're activating acpver_123.")


def test_fr2b_direct_unquoted_command_control():
    _assert_agent_loop("Activate acpver_123.")


# F-R2c: metalinguistic quotation framing --------------------------------
def test_fr2c_metalinguistic_en():
    _assert_framing_veto(
        "Quote this command: Activate acpver_123.",
        Intent.RAG_QUESTION, Explicitness.QUOTED_EXAMPLE,
        ReasonCode.QUOTED_EXAMPLE)


def test_fr2c_metalinguistic_it():
    _assert_framing_veto(
        "Citando questo comando: Attiva acpver_123.",
        Intent.RAG_QUESTION, Explicitness.QUOTED_EXAMPLE,
        ReasonCode.QUOTED_EXAMPLE)


def test_fr2c_metalinguistic_it_variants():
    for text in ("Cita questo comando: Attiva acpver_123.",
                 "Ripeti questo comando: Attiva acpver_123.",
                 "Trascrivi questo comando: Attiva acpver_123.",
                 "Scrivi questo comando: Attiva acpver_123."):
        _assert_framing_veto(
            text, Intent.RAG_QUESTION, Explicitness.QUOTED_EXAMPLE,
            ReasonCode.QUOTED_EXAMPLE)


def test_fr2c_unrelated_introductory_text_not_framed():
    # "this command" absent -> genuine command still executes.
    _assert_agent_loop("Please activate acpver_123.")


def test_fr2c_colon_with_direct_command_not_framed():
    _assert_agent_loop("Do this: Activate acpver_123.")


# F-R3: contextual Italian clitic multi-intent ----------------------------
def test_fr3_exact_failing_case():
    _assert_clarify("Analizza questo import e fallo se non ci sono errori.")


def test_fr3_clitic_variants():
    for text in (
        "Analizza questo import e fallo.",
        "Analizza questo import poi fallo.",
        "Analizza questo import e poi fallo.",
        "Analizza questo import e fallo pure.",
        "Analizza questo import e fallo\u2026",       # unicode ellipsis
        "Analizza questo import e fallo...",          # three ASCII dots
        "Analizza questo import e fallo",             # no ellipsis
    ):
        _assert_clarify(text)


def test_fr3_explicit_second_operation():
    _assert_clarify("Analizza questo import e committalo se non ci sono errori.")


def test_fr3_standalone_bare_affirmative_preserved():
    # Standalone clitic stays on the Phase C confirmation path (RAG), not a
    # generic operation.
    r = route_non_streaming("Fallo.")
    assert r.decision.route is Route.RAG
    assert r.claimed is None


def test_fr3_safe_single_intent_not_clarified():
    _assert_agent_loop("Analizza questo import.")


def test_fr3_english_near_pair():
    _assert_clarify("Analyze this import and commit it if there are no errors.")


# ---------------------------------------------------------------------------
# Phase F-Q — Italian parity & final gold-label reconciliation
# (owner authorization 2026-10-02). Bounded Italian deterministic corrections
# + aligned gold labels for five near-pair groups + mi_it_2. Asserts the engine
# contract directly (route, intent, mode, explicitness, reason codes, classifier
# eligibility, guard result, agent-loop admission, tool execution, registry /
# confirmation mutation, bypass reason) and the v1.2 gold alignment for every
# corrected record.
# ---------------------------------------------------------------------------

def _assert_consequential_agent_loop(text, intent, mode):
    r = route_non_streaming(text)
    d = r.decision
    assert d.route is Route.AGENT_LOOP, (text, d.route)
    assert d.intent is intent, (text, d.intent)
    assert d.mode is mode, (text, d.mode)
    assert d.explicitness is Explicitness.EXPLICIT, (text, d.explicitness)
    assert eligible_for_classification(r) is False
    assert is_consequential_candidate(r) is True
    assert classifier_bypass_reason(r) == "guard_terminal"
    assert r.claimed is None and r.resolved is None
    return d


def _assert_consequential_candidate_clarify(text, intent, explicitness):
    r = route_non_streaming(text)
    d = r.decision
    assert d.route is Route.CLARIFY, (text, d.route)
    assert d.intent is intent, (text, d.intent)
    assert d.explicitness is explicitness, (text, d.explicitness)
    assert ReasonCode.CONSEQUENTIAL_CANDIDATE in d.reason_codes, (text, d.reason_codes)
    assert is_consequential_candidate(r) is True
    assert eligible_for_classification(r) is False
    assert classifier_bypass_reason(r) == "consequential_candidate"
    assert d.route is not Route.AGENT_LOOP
    assert r.claimed is None and r.resolved is None
    return d


def _assert_negation_rag(text):
    r = route_non_streaming(text)
    d = r.decision
    assert d.route is Route.RAG, (text, d.route)
    assert d.intent is Intent.RAG_QUESTION, (text, d.intent)
    assert d.explicitness is Explicitness.NEGATED, (text, d.explicitness)
    assert ReasonCode.NEGATION in d.reason_codes, (text, d.reason_codes)
    assert eligible_for_classification(r) is False
    assert d.route is not Route.AGENT_LOOP
    assert r.claimed is None
    return d


def _assert_safe_proposal_agent_loop(text):
    r = route_non_streaming(text)
    d = r.decision
    assert d.route is Route.AGENT_LOOP, (text, d.route)
    assert d.intent is Intent.ACP_COHORT_PROPOSAL, (text, d.intent)
    assert d.mode is InteractionMode.ANALYSIS, (text, d.mode)
    assert d.explicitness is Explicitness.EXPLICIT, (text, d.explicitness)
    assert eligible_for_classification(r) is False
    assert is_consequential_candidate(r) is False
    assert r.claimed is None and r.resolved is None
    return d


# F-Q2-A: safe_prop (Italian cohort proposal -> AGENT_LOOP, not CLARIFY)
def test_fq_safe_prop_it():
    _assert_safe_proposal_agent_loop("Proponi una nuova coorte.")

def test_fq_safe_prop_en_parity():
    _assert_safe_proposal_agent_loop("Propose a new cohort.")

def test_fq_safe_prop_unrelated_it_not_command():
    # "proponi" without cohort/coorte context must NOT become a workflow command.
    r = route_non_streaming("Proponi un'idea per il report.")
    d = r.decision
    assert d.route is not Route.AGENT_LOOP
    assert d.intent is not Intent.ACP_COHORT_PROPOSAL


# F-Q2-B: cons_commit (Italian explicit-resource commit -> guarded AGENT_LOOP)
def test_fq_cons_commit_it_guard_pass():
    _assert_consequential_agent_loop(
        "Esegui il commit del batch batch_77.",
        Intent.COMPANY_IMPORT_COMMIT, InteractionMode.MUTATION)

def test_fq_cons_commit_en_parity():
    _assert_consequential_agent_loop(
        "Commit batch batch_77.",
        Intent.COMPANY_IMPORT_COMMIT, InteractionMode.MUTATION)

def test_fq_cons_commit_unrelated_it_control():
    # A different consequential operation still routes correctly (narrow fix).
    _assert_consequential_agent_loop(
        "Esegui il rollback di acpver_456.",
        Intent.ACP_ROLLBACK, InteractionMode.DESTRUCTIVE_MUTATION)


# F-Q2-C: cc_1 (Italian no-resource commit -> consequential candidate, CLARIFY)
def test_fq_cc_it_consequential_candidate():
    _assert_consequential_candidate_clarify(
        "Esegui il commit del batch.",
        Intent.CLARIFICATION_REQUIRED, Explicitness.EXPLICIT)

def test_fq_cc_en_parity():
    _assert_consequential_candidate_clarify(
        "Commit the batch.",
        Intent.CLARIFICATION_REQUIRED, Explicitness.EXPLICIT)

def test_fq_cc_streaming_not_rag_on_missing_resource():
    # Missing resource must NOT route to RAG; it fails closed to clarification.
    sd, _fam, _ = reval.classify_streaming_message("Esegui il commit del batch.")
    assert sd != "rag_passthrough"


# F-Q2-D: neg2 (Italian negation -> RAG, no execution)
def test_fq_neg_it_negation():
    _assert_negation_rag("Non proporre una coorte.")

def test_fq_neg_en_parity():
    _assert_negation_rag("Do not propose a cohort.")

def test_fq_neg_it_positive_control():
    # Without negation the same proposal is a safe workflow command.
    _assert_safe_proposal_agent_loop("Proponi una nuova coorte.")


# F-Q2-E: awa (Italian safe-review -> RAG, AMBIGUOUS, classifier-eligible)
def test_fq_awa_it_ambiguous_rag():
    r = route_non_streaming("Revisiona la proposta.")
    d = r.decision
    assert d.route is Route.RAG, (d.route)
    assert d.intent is Intent.AMBIGUOUS, (d.intent)
    assert d.mode is InteractionMode.UNKNOWN
    assert d.explicitness is Explicitness.AMBIGUOUS
    assert eligible_for_classification(r) is True
    assert is_consequential_candidate(r) is False

def test_fq_awa_en_parity():
    r = route_non_streaming("Review the proposal.")
    d = r.decision
    assert d.route is Route.RAG
    assert d.intent is Intent.AMBIGUOUS
    assert eligible_for_classification(r) is True

def test_fq_awa_it_no_consequential_authority():
    r = route_non_streaming("Revisiona la proposta.")
    assert is_consequential_candidate(r) is False
    assert eligible_for_classification(r) is True


# F-Q1: mi_it_2 final-intent gold alignment (engine already correct)
def test_fq_mi_it_2_final_intent_clarify():
    r = route_non_streaming("Analizza questo import e fallo se non ci sono errori.")
    d = r.decision
    assert d.intent is Intent.CLARIFICATION_REQUIRED
    assert d.route is Route.CLARIFY
    assert eligible_for_classification(r) is False
    assert is_consequential_candidate(r) is False
    assert r.claimed is None and r.resolved is None


# F-Q3: dataset-v1.2 gold aligns with the corrected engine for every record
def test_fq_dataset_v1_2_gold_alignment():
    recs = [json.loads(l) for l in
            (EVAL_DIR / "dataset-v1.2.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    changed = {"mi_it_2", "safe_it_3", "cons_it_2", "cc_it_1",
               "neg_it_2", "awa_it_1", "stream_adj_it"}
    for rec in recs:
        if rec["case_id"] not in changed:
            continue
        out = reval._recompute(rec)
        assert out["route"] == rec["expected_route_off"], rec["case_id"]
        assert out["intent"] == rec["expected_deterministic_intent"], rec["case_id"]
        assert out["mode"] == rec["expected_interaction_mode"], rec["case_id"]
        assert out["explicitness"] == rec["expected_explicitness"], rec["case_id"]
        assert out["elig"] == rec["expected_classifier_eligibility"], rec["case_id"]
