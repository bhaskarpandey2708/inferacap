"""Synthetic maximum-grid correctness and performance check for SW-004."""

from __future__ import annotations

import argparse
import json
import platform
import time
import tracemalloc
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sw004_simulator import run_scenario


def build_case(hours: int) -> dict:
    start = datetime(2026, 10, 26, tzinfo=timezone.utc)
    names = [f"R{i}" for i in range(8)]
    regions = [
        {
            "region": name,
            "model": "m1",
            "capacity_gpus": 8,
            "reserve_gpus": 0,
            "committed_gpus": 0,
            "billing_type": "on_demand",
            "requests_per_gpu_hour": 100,
            "max_utilization": "0.8",
            "price_usd_gpu_hour": str(8 - i),
            "source_kind": "synthetic",
            "source_ref": "core_stress_price_fixture",
        }
        for i, name in enumerate(names)
    ]
    routes = []
    for i, origin in enumerate(names):
        for j, destination in enumerate(names):
            if i == j:
                continue
            distance = abs(i - j)
            routes.append({
                "origin": origin,
                "destination": destination,
                "model": "m1",
                "residency_permission": True,
                "estimated_ttft_p95_ms": 80 + 12 * distance,
                "estimated_p95_ms": 140 + 35 * distance,
                "bytes_per_request": 1000,
                "egress_usd_gb": "0.10",
                "source_kind": "synthetic",
                "source_ref": "core_stress_route_fixture",
            })
    observations = []
    for hour in range(hours):
        stamp = (start + timedelta(hours=hour)).isoformat().replace("+00:00", "Z")
        for i, name in enumerate(names):
            observations.append({
                "scenario_id": "synthetic_core_stress",
                "timestamp_utc": stamp,
                "origin_region": name,
                "model_id": "m1",
                "requests": 180 + ((hour * 17 + i * 53) % 190),
                "mean_input_tokens": 100,
                "mean_output_tokens": 50,
                "max_ttft_ms": 100 if hour % 5 == 0 or hour % 7 == 0 else 250,
                "max_e2e_ms": 220 if hour % 7 == 0 else 500,
                "source_kind": "synthetic",
                "source_ref": "core_stress_demand_fixture",
            })
    return {
        "schema_version": 1,
        "scenario_id": "synthetic_core_stress",
        "currency": "USD",
        "start_utc": start.isoformat().replace("+00:00", "Z"),
        "hours": hours,
        "regions": regions,
        "observations": observations,
        "allowed_routes": routes,
    }


def check_report(case: dict, report: dict) -> dict:
    routes = {(r["origin"], r["destination"], r["model"]): r for r in case["allowed_routes"]}
    regions = {(r["region"], r["model"]): r for r in case["regions"]}
    assert report["status"] == "FEASIBLE_HEURISTIC"
    assert report["hours"] == case["hours"]
    assert len(report["hourly"]) == case["hours"]
    remote_assignments = 0
    for hour in report["hourly"]:
        origins = hour["origin_requests"]
        assigned = hour["candidate_assignments"]
        for origin_key, requests in origins.items():
            origin, model = origin_key.split("/", 1)
            assert sum(a["requests"] for a in assigned if a["origin"] == origin and a["model"] == model) == requests
        for (destination, model), region in regions.items():
            hosted = sum(a["requests"] for a in assigned if a["destination"] == destination and a["model"] == model)
            required = hour["candidate_required_gpus"][f"{destination}/{model}"]
            assert required <= region["capacity_gpus"] - region["reserve_gpus"]
            assert hosted <= required * region["requests_per_gpu_hour"] * Decimal(region["max_utilization"])
        for assignment in assigned:
            if assignment["origin"] == assignment["destination"]:
                continue
            remote_assignments += 1
            key = (assignment["origin"], assignment["destination"], assignment["model"])
            route = routes[key]
            budget = hour["origin_latency_budgets_ms"][f"{assignment['origin']}/{assignment['model']}"]
            assert Decimal(route["estimated_ttft_p95_ms"]) <= Decimal(budget["max_ttft_ms"])
            assert Decimal(route["estimated_p95_ms"]) <= Decimal(budget["max_e2e_ms"])
    baseline = Decimal(report["baseline_compute_usd"])
    candidate = Decimal(report["candidate_compute_usd"])
    lower = Decimal(report["perfect_pooling_compute_lower_bound_usd"])
    assert lower <= candidate <= baseline
    displayed_net = baseline - candidate - sum(
        Decimal(report[key]) for key in ("network_usd", "software_usd", "operations_usd", "migration_usd")
    ) + Decimal(report["rounding_adjustment_usd"])
    assert displayed_net == Decimal(report["net_current_cash_delta_usd"])
    return {"remote_assignment_rows": remote_assignments, "transfers": len(report["transfers"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=744)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--trace-memory", action="store_true", help="run one separate memory-traced replay")
    args = parser.parse_args()
    if not 1 <= args.hours <= 744 or not 1 <= args.runs <= 5:
        parser.error("hours must be 1-744 and runs 1-5")
    case = build_case(args.hours)
    times = []
    first = None
    checks = None
    for _ in range(args.runs):
        started = time.perf_counter()
        report = run_scenario(case)
        times.append(round(time.perf_counter() - started, 3))
        checks = check_report(case, report)
        if first is None:
            first = report
        else:
            assert report == first, "replay mismatch"
    traced = None
    if args.trace_memory:
        tracemalloc.start()
        started = time.perf_counter()
        report = run_scenario(case)
        traced = {
            "elapsed_seconds_with_tracemalloc": round(time.perf_counter() - started, 3),
            "peak_traced_mib": round(tracemalloc.get_traced_memory()[1] / 1048576, 2),
        }
        assert report == first, "memory-traced replay mismatch"
        check_report(case, report)
        tracemalloc.stop()
    print(json.dumps({
        "scenario": case["scenario_id"],
        "hours": args.hours,
        "region_model_records": len(case["regions"]),
        "observation_rows": len(case["observations"]),
        "allowed_route_edges": len(case["allowed_routes"]),
        "runs": args.runs,
        "elapsed_seconds_untraced": times,
        "memory_trace": traced,
        "deterministic": True,
        "invariant_checks": checks,
        "baseline_compute_usd": first["baseline_compute_usd"],
        "candidate_compute_usd": first["candidate_compute_usd"],
        "lower_bound_usd": first["perfect_pooling_compute_lower_bound_usd"],
        "modeled_net_usd": first["net_current_cash_delta_usd"],
        "python": platform.python_version(),
        "platform": platform.platform(),
        "latency_scope": "synthetic supplied route estimates only; no measured serving p95/p99",
    }, indent=2))


if __name__ == "__main__":
    main()
