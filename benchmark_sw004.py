"""Reproducible 30-day synthetic throughput check for the offline simulator."""

from __future__ import annotations

import argparse
import json
import platform
import time
import tracemalloc
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from sw004_simulator import parse_json_strict, run_scenario


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path(__file__).with_name("sw004_sample_scenario.json"))
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.runs <= 100:
        parser.error("--runs must be 1-100")

    raw = parse_json_strict(args.scenario.read_text(encoding="utf-8"))
    start = datetime.fromisoformat(raw["start_utc"].replace("Z", "+00:00"))
    original_hours = raw["hours"]
    by_hour: dict[str, list[dict]] = defaultdict(list)
    for row in raw["observations"]:
        by_hour[row["timestamp_utc"]].append(row)
    if len(by_hour) != original_hours:
        parser.error("sample must contain exactly one observation group per hour")
    raw["hours"] = 720
    end = (start + timedelta(hours=720)).isoformat().replace("+00:00", "Z")
    for region in raw["regions"]:
        for field in ("reservation_end_utc", "price_end_utc"):
            if field in region:
                region[field] = end
    raw["observations"] = []
    for hour in range(720):
        template_stamp = (start + timedelta(hours=hour % original_hours)).isoformat().replace("+00:00", "Z")
        stamp = (start + timedelta(hours=hour)).isoformat().replace("+00:00", "Z")
        for original in by_hour[template_stamp]:
            raw["observations"].append({**original, "timestamp_utc": stamp})

    tracemalloc.start()
    times = []
    first_report = None
    for _ in range(args.runs):
        started = time.perf_counter()
        report = run_scenario(raw)
        times.append(round(time.perf_counter() - started, 3))
        if first_report is None:
            first_report = report
        elif report != first_report:
            raise RuntimeError("repeat runs produced different reports")
    assert first_report is not None
    print(json.dumps({
        "scenario_origin": args.scenario.name,
        "template_hours": original_hours,
        "synthetic_hours": 720,
        "observation_rows": len(raw["observations"]),
        "runs": args.runs,
        "elapsed_seconds": times,
        "peak_traced_mib": round(tracemalloc.get_traced_memory()[1] / 1048576, 2),
        "deterministic": True,
        "scenario_sha256": first_report["scenario_sha256"],
        "status": first_report["status"],
        "python": platform.python_version(),
        "platform": platform.platform(),
    }, indent=2))


if __name__ == "__main__":
    main()
