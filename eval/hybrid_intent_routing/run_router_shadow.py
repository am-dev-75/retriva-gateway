#!/usr/bin/env python3
"""Spec 040 Phase D shadow acceptance runner (deployed gateway).

Sends the additive router dataset to the deployed Gateway in mode
``shadow`` with ``AGENT_SEMANTIC_ROUTER_ENABLED=true``.  Shadow records
the semantic decision but must NOT change the served route.  The runner
reads the content-free shadow diagnostics from
``/internal/routing/status`` and applies the Gate D safety/quality gates.

No production data is mutated: every request is a read-only chat turn;
the shadow router never enters the agent loop (FAMILY is not applied in
shadow), so no tool can execute.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

from retriva_gateway.agent.tools import build_default_tool_registry

GATE_FILE = Path(__file__).with_name("gate-router-thresholds-v2.json")


def _load_dataset(path: Path) -> list:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _headers(case_id: str) -> dict:
    return {
        "Content-Type": "application/json",
        "X-Correlation-ID": f"eval-{case_id}",
    }


def _post_chat(client: httpx.Client, gateway: str, case: dict,
               kb_id: str) -> dict:
    body = {
        "message": case["text"],
        "kb_ids": [kb_id],
        "stream": False,
        "session_id": f"eval-{case['case_id']}",
    }
    response = client.post(f"{gateway.rstrip('/')}/gateway/chat",
                           json=body, headers=_headers(case["case_id"]))
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        payload = {}
    return {
        "status": response.status_code,
        "content": payload.get("content") or "",
        "agent": payload.get("agent") or {},
        "error": payload.get("error") or {},
    }


def _get_shadow(client: httpx.Client, gateway: str, token: str) -> dict:
    response = client.get(
        f"{gateway.rstrip('/')}/gateway/internal/routing/status",
        headers={"X-Service-Token": token}, timeout=60.0)
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://localhost:8202")
    parser.add_argument("--dataset", default=str(
        Path(__file__).with_name("dataset-v2.jsonl")))
    parser.add_argument("--kb-id", default="cust_0007")
    parser.add_argument("--internal-token", default=os.environ.get(
        "GATEWAY_INTERNAL_SERVICE_TOKEN", ""))
    parser.add_argument("--output", default=str(
        Path(__file__).with_name("reports") / "router_shadow_report.json"))
    args = parser.parse_args()

    if not args.internal_token:
        print("missing --internal-token / GATEWAY_INTERNAL_SERVICE_TOKEN",
              file=sys.stderr)
        return 2

    gates = json.loads(GATE_FILE.read_text(encoding="utf-8"))["gates"]
    cases = _load_dataset(Path(args.dataset))
    results = []
    with httpx.Client(timeout=180.0) as client:
        for case in cases:
            served = _post_chat(client, args.gateway, case, args.kb_id)
            results.append({"case": case, "served": served})
        status = _get_shadow(client, args.gateway, args.internal_token)

    registry = build_default_tool_registry()
    destructive_names = {
        name for name in registry.names()
        if registry.get(name) is not None
        and registry.get(name).destructive
    }
    shadow = {
        record["correlation_id"]: record
        for record in (status.get("semantic_shadow_diagnostics", {})
                       .get("records") or [])
    }
    report = []
    failures = []
    destructive = 0
    router_routed_tool_calls = 0
    route_changes = 0
    matched = 0
    expected_total = 0
    for entry in results:
        case = entry["case"]
        served = entry["served"]
        record = shadow.get(f"eval-{case['case_id']}")
        expected = case["expected_semantic_decision"]
        tool_calls = served["agent"].get("tool_calls") or []
        destructive += sum(
            1 for call in tool_calls
            if call.get("tool") in destructive_names)
        if record is not None:
            router_routed_tool_calls += len(tool_calls)
        route_ok = None
        decision_ok = None
        if expected != "NOT_APPLICABLE":
            expected_total += 1
            if record is None:
                failures.append(
                    f"{case['case_id']}: no shadow diagnostic")
            else:
                decision_ok = record["decision"] == expected
                family_ok = (expected != "FAMILY"
                             or record.get("family") == case[
                                 "expected_family"])
                min_conf = case.get("expected_min_confidence")
                confidence_ok = (min_conf is None
                                 or (record.get("confidence") is not None
                                     and record["confidence"] >= min_conf))
                if decision_ok and family_ok and confidence_ok:
                    matched += 1
                else:
                    failures.append(
                        f"{case['case_id']}: decision={record['decision']} "
                        f"family={record.get('family')} "
                        f"confidence={record.get('confidence')}")
                route_ok = (record.get("route_served")
                            == case["expected_shadow_route"])
                if not route_ok:
                    route_changes += 1
                    failures.append(
                        f"{case['case_id']}: shadow route "
                        f"{record.get('route_served')} != "
                        f"{case['expected_shadow_route']}")
        if served["status"] != 200 or not served["content"].strip():
            failures.append(
                f"{case['case_id']}: chat status={served['status']} "
                f"content_len={len(served['content'])}")
        report.append({
            "case_id": case["case_id"],
            "text": case["text"],
            "deterministic_route": case["expected_deterministic_route"],
            "shadow_route": case["expected_shadow_route"],
            "expected_decision": expected,
            "expected_family": case.get("expected_family"),
            "actual_decision": (record or {}).get("decision"),
            "actual_family": (record or {}).get("family"),
            "actual_confidence": (record or {}).get("confidence"),
            "actual_route_served": (record or {}).get("route_served"),
            "served_content_len": len(served["content"]),
            "decision_ok": decision_ok,
            "route_ok": route_ok,
        })

    incident = next(
        (r for r in report if r["case_id"] == "router_incident_it"), None)
    incident_ok = bool(
        incident and incident["actual_decision"] == "FAMILY"
        and incident["actual_family"] == "CAMPAIGN"
        and incident["actual_confidence"] is not None
        and incident["actual_confidence"] >= 0.85
        and incident["actual_route_served"] == "CLARIFY")

    accuracy = (matched / expected_total) if expected_total else 0.0
    gate_results = {
        "incident_family_campaign": {
            "ok": incident_ok,
            "record": incident,
        },
        "router_decision_accuracy": {
            "ok": accuracy >= float(
                gates.get("router_decision_accuracy_min", 0.85)),
            "value": accuracy,
            "matched": matched,
            "total": expected_total,
        },
        "zero_destructive_executions": {
            "ok": destructive == 0,
            "value": destructive,
        },
        "zero_router_routed_tool_calls": {
            "ok": router_routed_tool_calls == 0,
            "value": router_routed_tool_calls,
        },
        "zero_shadow_route_changes": {
            "ok": route_changes == 0,
            "value": route_changes,
        },
        "all_served_non_empty": {
            "ok": all(r["served_content_len"] > 0 for r in report),
        },
    }
    output = {
        "schema_version": "2",
        "gateway": args.gateway,
        "dataset": args.dataset,
        "mode": status.get("mode"),
        "semantic_router": status.get("semantic_router"),
        "cases": report,
        "gates": gate_results,
        "failures": failures,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps(gate_results, indent=2, ensure_ascii=False))
    if failures:
        print("FAILURES:")
        for failure in failures:
            print(" -", failure)
    return 0 if all(g["ok"] for g in gate_results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
