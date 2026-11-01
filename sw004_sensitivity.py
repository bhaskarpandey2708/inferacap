"""Compare explicit offline scenarios as a deterministic sensitivity envelope."""

from __future__ import annotations

import argparse
import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from sw004_simulator import ScenarioError, parse_json_strict, run_scenario


def compare_scenarios(cases: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Compare like-period cases; the range is not a statistical confidence interval."""
    if not 2 <= len(cases) <= 10:
        raise ScenarioError("sensitivity: expected 2-10 explicit scenarios")
    names = [name for name, _ in cases]
    if any(not isinstance(name, str) or not name.strip() or len(name) > 100 or not name.isprintable() for name in names):
        raise ScenarioError("sensitivity: case names must be unique and 1-100 printable characters")
    if len(set(names)) != len(names):
        raise ScenarioError("sensitivity: case names must be unique and 1-100 characters")
    results = []
    reference = None
    for name, raw in cases:
        report = run_scenario(raw)
        fingerprint = (
            report["currency"], report["period_start_utc"], report["period_end_utc"],
            tuple(sorted(report["billing_types"])),
        )
        if reference is None:
            reference = fingerprint
        elif fingerprint != reference:
            raise ScenarioError("sensitivity: currency, period and region/model keys must match across cases")
        results.append({
            "case": name,
            "scenario_id": report["scenario_id"],
            "scenario_sha256": report["scenario_sha256"],
            "source_kinds": report["source_kinds"],
            "status": report["status"],
            "baseline_compute_usd": report["baseline_compute_usd"],
            "candidate_compute_usd": report["candidate_compute_usd"],
            "network_usd": report["network_usd"],
            "software_usd": report["software_usd"],
            "operations_usd": report["operations_usd"],
            "migration_usd": report["migration_usd"],
            "rounding_adjustment_usd": report["rounding_adjustment_usd"],
            "net_current_cash_delta_usd": report["net_current_cash_delta_usd"],
        })
    low = min(results, key=lambda row: (Decimal(row["net_current_cash_delta_usd"]), row["case"]))
    high = max(results, key=lambda row: (Decimal(row["net_current_cash_delta_usd"]), row["case"]))
    return {
        "analysis_type": "DETERMINISTIC_SCENARIO_ENVELOPE",
        "engine_version": report["version"],
        "input_schema_version": report["input_schema_version"],
        "currency": reference[0],
        "period_start_utc": reference[1],
        "period_end_utc": reference[2],
        "region_model_keys": list(reference[3]),
        "case_count": len(results),
        "minimum_net_current_cash_delta_usd": low["net_current_cash_delta_usd"],
        "minimum_case": low["case"],
        "maximum_net_current_cash_delta_usd": high["net_current_cash_delta_usd"],
        "maximum_case": high["case"],
        "includes_nonpositive_case": any(Decimal(row["net_current_cash_delta_usd"]) <= 0 for row in results),
        "cases": results,
        "limitations": [
            "The endpoints are only the minimum and maximum among the supplied scenarios; they are not probability or statistical confidence bounds.",
            "Each case uses a feasible heuristic, so its candidate cost is not proven globally minimal.",
            "Synthetic or operator-supplied assumptions do not verify customer contracts, route permission, latency or invoice avoidability.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="JSON report to write")
    parser.add_argument("scenarios", nargs="*", type=Path, help="2-10 complete scenario JSON files")
    parser.add_argument("--example", action="store_true", help="compare bundled synthetic case with $1000 software cost")
    args = parser.parse_args()
    if args.example:
        if args.scenarios:
            parser.error("--example cannot be combined with scenario files")
        sample = parse_json_strict(Path(__file__).with_name("sw004_sample_scenario.json").read_text(encoding="utf-8"))
        downside = copy.deepcopy(sample)
        downside["software_usd"] = "1000"
        cases = [("synthetic_base", sample), ("synthetic_software_1000_usd", downside)]
    else:
        if not 2 <= len(args.scenarios) <= 10:
            parser.error("expected 2-10 scenarios")
        cases = []
        for path in args.scenarios:
            if path.stat().st_size > 10_000_000:
                parser.error(f"{path.name}: scenario exceeds 10 MB")
            cases.append((path.stem, parse_json_strict(path.read_text(encoding="utf-8"))))
    report = compare_scenarios(cases)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
