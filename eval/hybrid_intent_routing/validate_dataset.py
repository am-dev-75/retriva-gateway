#!/usr/bin/env python3
"""Phase F dataset validator (Spec 001 / ADR-0002).

Dependency-free, offline validation of ``dataset-v1.jsonl`` against
``dataset-schema-v1.json`` (the closed gold-label schema) plus the accepted
cross-field rejection rules and privacy/leakage checks.  Makes NO network
calls (owner decision F-D2; constitution §29).

Exits non-zero on any rejection so it can gate CI / Gate F.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "dataset-schema-v1.json"
DATASET_PATH = HERE / "dataset-v1.jsonl"

# Forbidden production / confidential markers (synthetic_only must hold).
FORBIDDEN_PATTERNS = [
    re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}"),   # email
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),                      # openai-style key
    re.compile(r"api[_-]?key", re.I),
    re.compile(r"BEGIN (RSA|PRIVATE|OPENSSH) KEY"),
    re.compile(r"arn:aws:"),
    re.compile(r"https?://(?!retriva\.dev)"),                 # external URL (allow doc URLs)
]

REQUIRED_FAMILIES = [
    "informational_question", "safe_workflow", "consequential_workflow",
    "consequential_candidate", "negation", "hypothetical", "quotation",
    "code_framing", "prompt_writing", "multi_intent", "follow_up_reference",
    "bare_affirmative", "confirmation_path", "ambiguous_workflow_adjacent",
    "ambiguous_non_adjacent", "unsupported_operation", "streaming",
    "prompt_injection",
]

SAFETY_TAG_FAMILIES = {
    "consequential", "consequential_candidate", "multi_intent",
    "bare_affirmative", "injection", "quotation", "negation",
    "hypothetical", "code_framing", "prompt_writing", "unsupported",
}


class ValidationError(Exception):
    pass


def _check_type(value, typ):
    if typ == "string":
        return isinstance(value, str)
    if typ == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if typ == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if typ == "boolean":
        return isinstance(value, bool)
    if typ == "array":
        return isinstance(value, list)
    if typ == "object":
        return isinstance(value, dict)
    return True


def validate_instance(inst, schema, path="$"):
    typ = schema.get("type")
    if typ is not None and not _check_type(inst, typ):
        raise ValidationError(f"{path}: expected type {typ}, got {type(inst).__name__}")
    if "const" in schema and inst != schema["const"]:
        raise ValidationError(f"{path}: must equal {schema['const']!r}, got {inst!r}")
    if "enum" in schema and inst not in schema["enum"]:
        raise ValidationError(f"{path}: {inst!r} not in enum")
    if typ == "string":
        if "minLength" in schema and len(inst) < schema["minLength"]:
            raise ValidationError(f"{path}: too short")
        if "maxLength" in schema and len(inst) > schema["maxLength"]:
            raise ValidationError(f"{path}: too long")
        if "pattern" in schema and not re.search(schema["pattern"], inst):
            raise ValidationError(f"{path}: pattern mismatch")
    if typ == "integer" or typ == "number":
        if "minimum" in schema and inst < schema["minimum"]:
            raise ValidationError(f"{path}: < minimum")
        if "maximum" in schema and inst > schema["maximum"]:
            raise ValidationError(f"{path}: > maximum")
    if typ == "array":
        if "minItems" in schema and len(inst) < schema["minItems"]:
            raise ValidationError(f"{path}: too few items")
        if "items" in schema:
            for i, item in enumerate(inst):
                validate_instance(item, schema["items"], f"{path}[{i}]")
    if typ == "object":
        if "required" in schema:
            for req in schema["required"]:
                if req not in inst:
                    raise ValidationError(f"{path}: missing required {req}")
        if schema.get("additionalProperties") is False:
            known = set(schema.get("properties", {}))
            for key in inst:
                if key not in known:
                    raise ValidationError(f"{path}: unknown field {key!r}")
        if "properties" in schema:
            for key, subschema in schema["properties"].items():
                if key in inst:
                    validate_instance(inst[key], subschema, f"{path}.{key}")


def load_records():
    if not DATASET_PATH.exists():
        raise ValidationError(f"dataset not found: {DATASET_PATH}")
    records = []
    with DATASET_PATH.open(encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append((ln, json.loads(line)))
            except json.JSONDecodeError as exc:
                raise ValidationError(f"line {ln}: invalid JSON ({exc})")
    return records


def cross_field_checks(records):
    errors = []
    ids = {}
    partitions_by_pair = {}
    for ln, r in records:
        cid = r["case_id"]
        if cid in ids:
            errors.append(f"line {ln}: duplicate case_id {cid!r}")
        ids[cid] = ln

        # contradictory: consequential marked classifier-eligible
        if r["expected_classifier_eligibility"] and (
                "consequential" in r["safety_tags"]
                or "consequential_candidate" in r["safety_tags"]):
            errors.append(f"{cid}: consequential marked classifier-eligible")
        # contradictory: bare affirmative marked classifier-eligible
        if r["expected_classifier_eligibility"] and "bare_affirmative" in r["safety_tags"]:
            errors.append(f"{cid}: bare affirmative marked classifier-eligible")
        # contradictory: multi-intent marked executable
        if "multi_intent" in r["safety_tags"] and r["expected_agent_loop_admission"]:
            errors.append(f"{cid}: multi-intent marked executable")
        # contradictory: streaming consequential command marked RAG solely
        # because resource absent
        if (r["case_family"] == "streaming"
                and "consequential_candidate" in r["safety_tags"]
                and r["expected_streaming_behavior"] == "rag_passthrough"):
            errors.append(f"{cid}: streaming consequential candidate marked rag_passthrough")
        # contradictory: classifier call for ineligible turn
        if (not r["expected_classifier_eligibility"]
                and r["expected_classifier_call_count"] != 0):
            errors.append(f"{cid}: classifier call for ineligible turn")
        # contradictory: confirmation claim without confirmation family
        if r["expected_confirmation_claim"] == "claimed" and \
                "confirmation" not in r["safety_tags"]:
            errors.append(f"{cid}: claimed without confirmation tag")
        # missing safety labels
        if not r["safety_tags"] and r["case_family"] in (
                "consequential_candidate", "multi_intent", "bare_affirmative",
                "prompt_injection", "quotation", "unsupported_operation"):
            errors.append(f"{cid}: missing safety tags for {r['case_family']}")
        # synthetic-only declaration
        if r.get("synthetic_only") is not True:
            errors.append(f"{cid}: synthetic_only is not true")
        # forbidden production markers
        for pat in FORBIDDEN_PATTERNS:
            if pat.search(r["synthetic_text"]):
                errors.append(f"{cid}: forbidden pattern {pat.pattern!r} in text")
        # adjudication completeness for scored partitions
        if r["partition"] == "test" and r["adjudication_status"] == "needs_owner_decision":
            errors.append(f"{cid}: needs_owner_decision in scored test partition")
        # leakage: near_pair group confined to one partition
        grp = r["near_pair_group"]
        part = r["partition"]
        if grp in partitions_by_pair and partitions_by_pair[grp] != part:
            errors.append(f"{cid}: near_pair_group {grp!r} split across partitions")
        partitions_by_pair[grp] = part
    return errors


def coverage_checks(records):
    errors = []
    fams = {r["case_family"] for _, r in records}
    for f in REQUIRED_FAMILIES:
        if f not in fams:
            errors.append(f"missing required family: {f}")
    # language balance per family
    by_fam = {}
    for _, r in records:
        by_fam.setdefault(r["case_family"], set()).add(r["language"])
    for f, langs in by_fam.items():
        if "en" not in langs or "it" not in langs:
            errors.append(f"family {f} missing language balance: {sorted(langs)}")
    return errors


def main():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    records = load_records()
    print(f"validating {len(records)} records against schema "
          f"{schema.get('$id','?')}", file=sys.stderr)
    errs = []
    for ln, r in records:
        try:
            validate_instance(r, schema, f"rec:{r['case_id']}")
        except ValidationError as exc:
            errs.append(str(exc))
    errs += cross_field_checks(records)
    errs += coverage_checks(records)

    if errs:
        for e in errs:
            print(f"REJECT: {e}", file=sys.stderr)
        print(f"FAILED: {len(errs)} rejection(s)", file=sys.stderr)
        return 1
    print("PASSED: dataset valid, leakage-controlled, synthetic-only, "
          "fully covered", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
