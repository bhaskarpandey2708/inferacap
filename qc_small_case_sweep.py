"""Independent finite-grid accounting and route check for the offline engine."""

from __future__ import annotations

import itertools
import json
import time
from decimal import Decimal, ROUND_CEILING

from sw004_simulator import run_scenario


DEMAND = (0, 1, 9, 10, 11, 19, 20)
REGIONS = ("A", "B")


def whole_gpus(requests: int) -> int:
    return int((Decimal(requests) / Decimal(10)).to_integral_value(rounding=ROUND_CEILING))


def fixture(demand: tuple[int, int], prices: tuple[int, int], edges: tuple[bool, bool], strict: bool, expensive_network: bool) -> dict:
    regions = []
    observations = []
    for i, name in enumerate(REGIONS):
        regions.append({
            "region": name, "model": "m", "capacity_gpus": 2, "reserve_gpus": 0,
            "committed_gpus": 0, "billing_type": "on_demand",
            "requests_per_gpu_hour": 10, "max_utilization": "1",
            "price_usd_gpu_hour": str(prices[i]),
            "source_kind": "synthetic", "source_ref": "finite_grid",
        })
        observations.append({
            "scenario_id": "finite_grid", "timestamp_utc": "2026-10-27T00:00:00Z",
            "origin_region": name, "model_id": "m", "requests": demand[i],
            "mean_input_tokens": 1, "mean_output_tokens": 1,
            "max_ttft_ms": 79 if strict else 100, "max_e2e_ms": 200,
            "source_kind": "synthetic", "source_ref": "finite_grid",
        })
    routes = []
    for i, enabled in enumerate(edges):
        if enabled:
            routes.append({
                "origin": REGIONS[i], "destination": REGIONS[1 - i], "model": "m",
                "residency_permission": True, "estimated_ttft_p95_ms": 80,
                "estimated_p95_ms": 200,
                "bytes_per_request": 1_000_000_000 if expensive_network else 0,
                "egress_usd_gb": "2" if expensive_network else "0",
                "source_kind": "synthetic", "source_ref": "finite_grid",
            })
    return {
        "schema_version": 1, "scenario_id": "finite_grid", "currency": "USD",
        "start_utc": "2026-10-27T00:00:00Z", "hours": 1,
        "regions": regions, "observations": observations, "allowed_routes": routes,
    }


def check(case: dict, report: dict) -> bool:
    prices = {r["region"]: Decimal(r["price_usd_gpu_hour"]) for r in case["regions"]}
    demand = {r["origin_region"]: r["requests"] for r in case["observations"]}
    budgets = {r["origin_region"]: Decimal(r["max_ttft_ms"]) for r in case["observations"]}
    permitted = {(r["origin"], r["destination"]): r for r in case["allowed_routes"]}
    assignments = report["hourly"][0]["candidate_assignments"]
    hosted = {r: 0 for r in REGIONS}
    assigned = {r: 0 for r in REGIONS}
    network = Decimal(0)
    remote = False
    for row in assignments:
        origin, dest, amount = row["origin"], row["destination"], row["requests"]
        assert row["model"] == "m" and origin in REGIONS and dest in REGIONS
        assert isinstance(amount, int) and amount > 0
        hosted[dest] += amount
        assigned[origin] += amount
        if origin != dest:
            remote = True
            route = permitted[(origin, dest)]
            assert Decimal(route["estimated_ttft_p95_ms"]) <= budgets[origin]
            assert Decimal(route["estimated_p95_ms"]) <= Decimal(200)
            network += Decimal(amount * route["bytes_per_request"]) / Decimal(1_000_000_000) * Decimal(route["egress_usd_gb"])
    assert assigned == demand
    assert all(hosted[r] <= 20 for r in REGIONS)
    baseline = sum((Decimal(whole_gpus(demand[r])) * prices[r] for r in REGIONS), Decimal(0))
    candidate = sum((Decimal(whole_gpus(hosted[r])) * prices[r] for r in REGIONS), Decimal(0))
    assert report["baseline_compute_usd"] == f"{baseline:.2f}"
    assert report["candidate_compute_usd"] == f"{candidate:.2f}"
    assert report["network_usd"] == f"{network:.2f}"
    assert report["net_current_cash_delta_usd"] == f"{baseline - candidate - network:.2f}"
    assert candidate + network <= baseline
    assert Decimal(report["perfect_pooling_compute_lower_bound_usd"]) <= candidate
    assert report["hourly"][0]["candidate_required_gpus"] == {f"{r}/m": int(whole_gpus(hosted[r])) for r in REGIONS}
    return remote


def main() -> None:
    started = time.perf_counter()
    count = remote_cases = 0
    for da, db, pa, pb, ab, ba, strict, network in itertools.product(DEMAND, DEMAND, (1, 3), (1, 3), (False, True), (False, True), (False, True), (False, True)):
        case = fixture((da, db), (pa, pb), (ab, ba), strict, network)
        report = run_scenario(case)
        remote_cases += check(case, report)
        count += 1
    print(json.dumps({"case_count": count, "cases_with_remote_assignments": remote_cases,
                      "elapsed_seconds": round(time.perf_counter() - started, 3),
                      "checks": "independent conservation, ordered edge, supplied latency, capacity, invoice, network, nonnegative gain, compute bound"}, indent=2))


if __name__ == "__main__":
    main()
