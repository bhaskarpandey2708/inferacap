"""Offline, deterministic SW-004 capacity economics prototype.

This module is independently written for the local simulator. It does not
implement or import the SkyWalker research artifact.
"""

from __future__ import annotations

import hashlib
import json
import re
import csv
from io import StringIO
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from pathlib import Path
from typing import Any


VERSION = "0.7.3"
SCHEMA_VERSION = 1
MAX_NUMERIC = Decimal("1000000000")
MIN_NONZERO_DECIMAL = Decimal("0.000001")
MAX_SOURCE_REF_LENGTH = 1024
MAX_TRANSFER_STEPS = 10_000


class ScenarioError(ValueError):
    """An input or feasibility failure with a user-visible explanation."""


def parse_json_strict(text: str) -> Any:
    """Reject ambiguous JSON objects before creating an audit hash or report."""
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ScenarioError(f"JSON: duplicate field {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ScenarioError(f"JSON: nonstandard number {value!r}")

    try:
        return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except RecursionError as exc:
        raise ScenarioError("JSON: nesting exceeds parser limit") from exc


def _reject_unknown_fields(value: dict, allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        first = sorted(unknown, key=str)[0]
        raise ScenarioError(f"{label}: unsupported field {first!r}")


def _decimal(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ScenarioError(f"{label}: boolean is not a number")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ScenarioError(f"{label}: invalid number") from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ScenarioError(f"{label}: expected {'positive' if positive else 'nonnegative'} finite number")
    if result == 0:
        return Decimal(0)
    if result > MAX_NUMERIC or (result != 0 and result < MIN_NONZERO_DECIMAL):
        raise ScenarioError(f"{label}: outside prototype numeric range 0 or 0.000001-1000000000")
    if len(result.normalize().as_tuple().digits) > 18:
        raise ScenarioError(f"{label}: expected at most 18 significant digits")
    return result


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 1_000_000_000:
        raise ScenarioError(f"{label}: expected nonnegative integer at most 1000000000")
    return value


def _source_ref(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_SOURCE_REF_LENGTH or not value.isprintable():
        raise ScenarioError(f"{label}: expected 1-1024 printable characters")
    return value


def _utc_hour(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ScenarioError(f"{label}: expected UTC timestamp ending Z")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScenarioError(f"{label}: invalid timestamp") from exc
    if result.tzinfo != timezone.utc or (result.minute, result.second, result.microsecond) != (0, 0, 0):
        raise ScenarioError(f"{label}: expected an aligned UTC hour")
    return result


def _gpus(requests: int, throughput: Decimal, utilization: Decimal) -> int:
    if requests == 0:
        return 0
    return int((Decimal(requests) / (throughput * utilization)).to_integral_value(rounding=ROUND_CEILING))


def _invoice(required: int, row: dict) -> Decimal:
    """Keep the reservation invoice fixed and price only overflow at its marginal rate."""
    return Decimal(row["committed"]) * row["price"] + Decimal(max(required - row["committed"], 0)) * row["overflow_price"]


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _exact_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _perfect_pooling_compute_lower_bound(demand: dict[tuple[str, str], int], regions: dict) -> Decimal:
    """Relax routes and whole-GPU purchases, retaining fixed commitment invoices.

    All requests of one model may use any compatible region. Paid commitment
    capacity is used first; remaining demand buys fractional GPU capacity in
    increasing USD/request order. No network or software cost is included.
    """
    total = sum((Decimal(row["committed"]) * row["price"] for row in regions.values()), Decimal(0))
    for model in sorted({key[1] for key in regions}):
        pending = Decimal(sum(requests for (region, model_id), requests in demand.items() if model_id == model))
        marginal = []
        for (region, model_id), row in sorted(regions.items()):
            if model_id != model:
                continue
            per_gpu = row["throughput"] * row["utilization"]
            free_gpus = min(row["committed"], row["capacity"])
            pending -= Decimal(free_gpus) * per_gpu
            extra_gpus = max(row["capacity"] - free_gpus, 0)
            if extra_gpus:
                marginal.append((row["overflow_price"] / per_gpu, region, Decimal(extra_gpus) * per_gpu, row["overflow_price"], per_gpu))
        pending = max(pending, Decimal(0))
        for _, _, request_capacity, price_per_gpu, requests_per_gpu in sorted(marginal):
            served = min(pending, request_capacity)
            total += served * price_per_gpu / requests_per_gpu
            pending -= served
            if pending == 0:
                break
        if pending > 0:
            raise ScenarioError(f"perfect-pooling bound INFEASIBLE for model {model}")
    return total


def _validate(raw: dict[str, Any]) -> tuple[dict, list[dict], dict, dict]:
    if not isinstance(raw, dict):
        raise ScenarioError("scenario: expected JSON object")
    _reject_unknown_fields(raw, {
        "schema_version", "scenario_id", "currency", "start_utc", "hours", "regions", "observations",
        "allowed_routes", "software_usd", "operations_usd", "migration_usd",
    }, "scenario")
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != SCHEMA_VERSION:
        raise ScenarioError(f"schema_version: expected integer {SCHEMA_VERSION}")
    scenario_id = raw.get("scenario_id")
    if not isinstance(scenario_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", scenario_id):
        raise ScenarioError("scenario_id: expected 1-100 safe ASCII characters")
    currency = raw.get("currency")
    if currency != "USD":
        raise ScenarioError("currency: prototype accepts USD only")
    start = _utc_hour(raw.get("start_utc"), "start_utc")
    hours = _integer(raw.get("hours"), "hours")
    if not 1 <= hours <= 24 * 31:
        raise ScenarioError("hours: expected 1-744")
    end = start + timedelta(hours=hours)
    entries = raw.get("regions")
    if not isinstance(entries, list) or not 2 <= len(entries) <= 8:
        raise ScenarioError("regions: expected 2-8 region/model capacity records")
    regions: dict[tuple[str, str], dict] = {}
    for i, row in enumerate(entries):
        if not isinstance(row, dict):
            raise ScenarioError(f"regions[{i}]: expected object")
        _reject_unknown_fields(row, {
            "region", "model", "capacity_gpus", "reserve_gpus", "committed_gpus", "owned_gpus",
            "billing_type", "requests_per_gpu_hour", "max_utilization",
            "price_usd_gpu_hour", "overflow_price_usd_gpu_hour", "reservation_region",
            "reservation_start_utc", "reservation_end_utc", "price_start_utc",
            "price_end_utc", "on_demand_price_windows", "source_kind", "source_ref",
        }, f"regions[{i}]")
        region_name, model_name = row.get("region"), row.get("model")
        if not all(isinstance(s, str) and s.strip() and len(s) <= 80 and s.isprintable() for s in (region_name, model_name)):
            raise ScenarioError(f"regions[{i}]: invalid region/model")
        key = (region_name, model_name)
        if key in regions:
            raise ScenarioError(f"regions[{i}]: invalid or duplicate region/model")
        capacity = _integer(row.get("capacity_gpus"), f"regions[{i}].capacity_gpus")
        reserve = _integer(row.get("reserve_gpus"), f"regions[{i}].reserve_gpus")
        billing_type = row.get("billing_type")
        if billing_type not in ("on_demand", "noncancellable_reservation", "owned"):
            raise ScenarioError(f"regions[{i}].billing_type: prototype accepts on_demand, noncancellable_reservation or owned")
        if billing_type == "owned":
            if "committed_gpus" in row:
                raise ScenarioError(f"regions[{i}]: owned capacity cannot contain committed_gpus")
            owned = _integer(row.get("owned_gpus"), f"regions[{i}].owned_gpus")
            if owned == 0 or owned != capacity:
                raise ScenarioError(f"regions[{i}]: owned_gpus must equal positive capacity_gpus")
            committed = owned
        else:
            if "owned_gpus" in row:
                raise ScenarioError(f"regions[{i}]: owned_gpus requires owned billing_type")
            owned = 0
            committed = _integer(row.get("committed_gpus"), f"regions[{i}].committed_gpus")
        if reserve > capacity or committed > capacity:
            raise ScenarioError(f"regions[{i}]: reserve/commitment exceeds capacity")
        if (billing_type == "on_demand" and committed != 0) or (billing_type == "noncancellable_reservation" and committed == 0):
            raise ScenarioError(f"regions[{i}]: billing_type and committed_gpus disagree")
        scheduled = "on_demand_price_windows" in row
        if scheduled and billing_type != "on_demand":
            raise ScenarioError(f"regions[{i}]: price windows require on_demand billing")
        if scheduled and any(field in row for field in ("price_usd_gpu_hour", "price_start_utc", "price_end_utc")):
            raise ScenarioError(f"regions[{i}]: price windows cannot mix with a flat on-demand price")
        price = Decimal(0) if scheduled else _decimal(row.get("price_usd_gpu_hour"), f"regions[{i}].price_usd_gpu_hour")
        if billing_type == "owned" and price != 0:
            raise ScenarioError(f"regions[{i}]: owned capacity requires zero current GPU invoice rate")
        source_kind = row.get("source_kind")
        if source_kind not in ("synthetic", "operator_supplied", "measured"):
            raise ScenarioError(f"regions[{i}]: missing provenance")
        reservation_fields = (
            "overflow_price_usd_gpu_hour", "reservation_region",
            "reservation_start_utc", "reservation_end_utc",
        )
        price_fields = ("price_start_utc", "price_end_utc")
        price_windows = []
        if billing_type == "owned":
            if any(field in row for field in reservation_fields + price_fields):
                raise ScenarioError(f"regions[{i}]: owned capacity cannot contain rental or reservation terms")
            overflow_price = Decimal(0)
            reservation_region = None
            reservation_start = None
            reservation_end = None
            price_start = None
            price_end = None
            price_window_assumed = False
            supplied = False
        elif billing_type == "noncancellable_reservation":
            if any(field in row for field in price_fields):
                raise ScenarioError(f"regions[{i}]: reservation billing uses its contract window, not on-demand price dates")
            supplied = all(field in row for field in reservation_fields)
            if any(field in row for field in reservation_fields) and not supplied:
                raise ScenarioError(f"regions[{i}]: reservation terms must be all supplied or all omitted")
            if not supplied and source_kind != "synthetic":
                raise ScenarioError(f"regions[{i}]: actual reservation requires explicit overflow rate, region and UTC window")
            overflow_price = _decimal(
                row.get("overflow_price_usd_gpu_hour", row["price_usd_gpu_hour"]),
                f"regions[{i}].overflow_price_usd_gpu_hour",
            )
            reservation_region = row.get("reservation_region", region_name)
            reservation_start = _utc_hour(row.get("reservation_start_utc", raw["start_utc"]), f"regions[{i}].reservation_start_utc")
            reservation_end = _utc_hour(row.get("reservation_end_utc", end.isoformat().replace("+00:00", "Z")), f"regions[{i}].reservation_end_utc")
            if reservation_region != region_name or reservation_start > start or reservation_end < end:
                raise ScenarioError(f"regions[{i}]: reservation region/window does not cover the scenario")
            price_start = None
            price_end = None
            price_window_assumed = False
        else:
            if any(field in row for field in reservation_fields):
                raise ScenarioError(f"regions[{i}]: on-demand billing cannot contain reservation terms")
            if scheduled:
                windows = row["on_demand_price_windows"]
                if not isinstance(windows, list) or not 1 <= len(windows) <= hours:
                    raise ScenarioError(f"regions[{i}].on_demand_price_windows: expected 1-{hours} UTC windows")
                previous_end = None
                for j, window in enumerate(windows):
                    label = f"regions[{i}].on_demand_price_windows[{j}]"
                    if not isinstance(window, dict):
                        raise ScenarioError(f"{label}: expected object")
                    _reject_unknown_fields(window, {"start_utc", "end_utc", "price_usd_gpu_hour", "source_kind", "source_ref"}, label)
                    window_start = _utc_hour(window.get("start_utc"), f"{label}.start_utc")
                    window_end = _utc_hour(window.get("end_utc"), f"{label}.end_utc")
                    if window_end <= window_start or (previous_end is not None and window_start != previous_end):
                        raise ScenarioError(f"{label}: price windows must be positive and contiguous")
                    if window.get("source_kind") not in ("synthetic", "operator_supplied", "measured"):
                        raise ScenarioError(f"{label}: missing price provenance")
                    price_windows.append({
                        "start": window_start, "end": window_end,
                        "price": _decimal(window.get("price_usd_gpu_hour"), f"{label}.price_usd_gpu_hour"),
                        "source_kind": window["source_kind"],
                        "source_ref": _source_ref(window.get("source_ref"), f"{label}.source_ref"),
                    })
                    previous_end = window_end
                if price_windows[0]["start"] > start or price_windows[-1]["end"] < end:
                    raise ScenarioError(f"regions[{i}]: on-demand price windows do not cover the scenario")
                price = price_windows[0]["price"]
                price_start = None
                price_end = None
                price_window_assumed = False
                overflow_price = price
                reservation_region = None
                reservation_start = None
                reservation_end = None
            else:
                supplied_price_window = all(field in row for field in price_fields)
                if any(field in row for field in price_fields) and not supplied_price_window:
                    raise ScenarioError(f"regions[{i}]: on-demand price dates must both be supplied")
                if not supplied_price_window and source_kind != "synthetic":
                    raise ScenarioError(f"regions[{i}]: actual on-demand price requires explicit UTC window")
                price_start = _utc_hour(row.get("price_start_utc", raw["start_utc"]), f"regions[{i}].price_start_utc")
                price_end = _utc_hour(row.get("price_end_utc", end.isoformat().replace("+00:00", "Z")), f"regions[{i}].price_end_utc")
                if price_start > start or price_end < end:
                    raise ScenarioError(f"regions[{i}]: on-demand price window does not cover the scenario")
                price_window_assumed = not supplied_price_window
                overflow_price = price
                reservation_region = None
                reservation_start = None
                reservation_end = None
        utilization = _decimal(row.get("max_utilization"), f"regions[{i}].max_utilization", positive=True)
        if utilization > 1:
            raise ScenarioError(f"regions[{i}].max_utilization: expected <= 1")
        regions[key] = {
            "capacity": capacity - reserve,
            "committed": committed,
            "owned": owned,
            "throughput": _decimal(row.get("requests_per_gpu_hour"), f"regions[{i}].requests_per_gpu_hour", positive=True),
            "utilization": utilization,
            "price": price,
            "overflow_price": overflow_price,
            "reservation_region": reservation_region,
            "reservation_start": reservation_start,
            "reservation_end": reservation_end,
            "reservation_terms_assumed": billing_type == "noncancellable_reservation" and not supplied,
            "price_start": price_start,
            "price_end": price_end,
            "price_window_assumed": price_window_assumed,
            "price_windows": price_windows,
            "billing_type": billing_type,
            "source_kind": source_kind,
            "source_ref": _source_ref(row.get("source_ref"), f"regions[{i}].source_ref"),
        }
    if len({f"{region}/{model}" for region, model in regions}) != len(regions):
        raise ScenarioError("regions: ambiguous region/model report key")
    observations = raw.get("observations")
    if not isinstance(observations, list) or len(observations) > 8 * 24 * 31:
        raise ScenarioError("observations: invalid or oversized list")
    expected = {(start + timedelta(hours=h), region, model) for h in range(hours) for region, model in regions}
    seen: set[tuple] = set()
    normalized: list[dict] = []
    for i, row in enumerate(observations):
        if not isinstance(row, dict):
            raise ScenarioError(f"observations[{i}]: expected object")
        _reject_unknown_fields(row, {
            "scenario_id", "timestamp_utc", "origin_region", "model_id", "requests",
            "mean_input_tokens", "mean_output_tokens", "max_ttft_ms", "max_e2e_ms",
            "source_kind", "source_ref",
        }, f"observations[{i}]")
        if row.get("scenario_id") != scenario_id:
            raise ScenarioError(f"observations[{i}].scenario_id: does not match scenario")
        stamp = _utc_hour(row.get("timestamp_utc"), f"observations[{i}].timestamp_utc")
        if not isinstance(row.get("origin_region"), str) or not isinstance(row.get("model_id"), str):
            raise ScenarioError(f"observations[{i}]: invalid region/model")
        key = (stamp, row.get("origin_region"), row.get("model_id"))
        if key not in expected or key in seen:
            raise ScenarioError(f"observations[{i}]: unknown/duplicate region-model-hour {key}")
        seen.add(key)
        requests = _integer(row.get("requests"), f"observations[{i}].requests")
        _decimal(row.get("mean_input_tokens"), f"observations[{i}].mean_input_tokens")
        _decimal(row.get("mean_output_tokens"), f"observations[{i}].mean_output_tokens")
        max_ttft = _decimal(row.get("max_ttft_ms"), f"observations[{i}].max_ttft_ms", positive=True)
        max_latency = _decimal(row.get("max_e2e_ms"), f"observations[{i}].max_e2e_ms", positive=True)
        if max_ttft > max_latency:
            raise ScenarioError(f"observations[{i}]: TTFT budget exceeds end-to-end budget")
        if row.get("source_kind") not in ("synthetic", "operator_supplied", "measured"):
            raise ScenarioError(f"observations[{i}]: missing provenance")
        normalized.append({"stamp": stamp, "region": key[1], "model": key[2], "requests": requests, "max_ttft": max_ttft, "max_latency": max_latency, "source_kind": row["source_kind"], "source_ref": _source_ref(row.get("source_ref"), f"observations[{i}].source_ref")})
    missing = expected - seen
    if missing:
        first = sorted(missing)[0]
        raise ScenarioError(f"observations: {len(missing)} missing region-model-hour records, first={first}")
    route_entries = raw.get("allowed_routes", [])
    if not isinstance(route_entries, list):
        raise ScenarioError("allowed_routes: expected list")
    routes: dict[tuple[str, str, str], dict] = {}
    for i, row in enumerate(route_entries):
        if not isinstance(row, dict):
            raise ScenarioError(f"allowed_routes[{i}]: expected object")
        _reject_unknown_fields(row, {
            "origin", "destination", "model", "residency_permission", "estimated_p95_ms", "estimated_ttft_p95_ms",
            "bytes_per_request", "egress_usd_gb", "source_kind", "source_ref",
        }, f"allowed_routes[{i}]")
        if not all(isinstance(row.get(field), str) for field in ("origin", "destination", "model")):
            raise ScenarioError(f"allowed_routes[{i}]: invalid edge")
        key = (row.get("origin"), row.get("destination"), row.get("model"))
        if key in routes or key[0] == key[1] or (key[0], key[2]) not in regions or (key[1], key[2]) not in regions:
            raise ScenarioError(f"allowed_routes[{i}]: invalid or duplicate edge")
        if row.get("residency_permission") is not True:
            raise ScenarioError(f"allowed_routes[{i}]: permission must be true")
        route_p95 = _decimal(row.get("estimated_p95_ms"), f"allowed_routes[{i}].estimated_p95_ms", positive=True)
        route_ttft = _decimal(row.get("estimated_ttft_p95_ms"), f"allowed_routes[{i}].estimated_ttft_p95_ms", positive=True)
        if route_ttft > route_p95:
            raise ScenarioError(f"allowed_routes[{i}]: TTFT p95 exceeds end-to-end p95")
        routes[key] = {
            "p95_ms": route_p95,
            "ttft_p95_ms": route_ttft,
            "bytes": _integer(row.get("bytes_per_request"), f"allowed_routes[{i}].bytes_per_request"),
            "egress": _decimal(row.get("egress_usd_gb"), f"allowed_routes[{i}].egress_usd_gb"),
            "source_kind": row.get("source_kind"),
            "source_ref": _source_ref(row.get("source_ref"), f"allowed_routes[{i}].source_ref"),
        }
        if routes[key]["source_kind"] not in ("synthetic", "operator_supplied", "measured"):
            raise ScenarioError(f"allowed_routes[{i}]: missing provenance")
    extras = {}
    for field in ("software_usd", "operations_usd", "migration_usd"):
        extras[field] = _decimal(raw.get(field, 0), field)
    return {"id": scenario_id, "schema_version": SCHEMA_VERSION, "start": start, "hours": hours, "currency": currency}, normalized, regions, {"routes": routes, "extras": extras}


def run_scenario(raw: dict[str, Any]) -> dict[str, Any]:
    """Return an auditable local baseline and deterministic feasible candidate.

    Candidate uses positive-cost-reduction transfers, so it is a
    feasible heuristic and not a proof of globally optimal routing.
    """
    with localcontext() as context:
        context.prec = 50
        return _run_scenario_with_context(raw)


def _run_scenario_with_context(raw: dict[str, Any]) -> dict[str, Any]:
    meta, observations, regions, config = _validate(raw)
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    scenario_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    by_hour: dict[datetime, dict[tuple[str, str], dict]] = defaultdict(dict)
    for row in observations:
        by_hour[row["stamp"]][(row["region"], row["model"])] = row
    baseline_compute = Decimal(0)
    candidate_compute = Decimal(0)
    fixed_commitment = Decimal(0)
    baseline_variable_usage = Decimal(0)
    candidate_variable_usage = Decimal(0)
    perfect_pooling_bound = Decimal(0)
    network = Decimal(0)
    baseline_gpu_hours = 0
    candidate_gpu_hours = 0
    transfers: list[dict] = []
    hourly: list[dict] = []
    for stamp in sorted(by_hour):
        hour_regions = {}
        for key, row in regions.items():
            if row["price_windows"]:
                window = next(window for window in row["price_windows"] if window["start"] <= stamp < window["end"])
                hour_regions[key] = {**row, "price": window["price"], "overflow_price": window["price"]}
            else:
                hour_regions[key] = row
        demand = {key: by_hour[stamp][key]["requests"] for key in regions}
        assigned = {(origin, origin, model): requests for (origin, model), requests in demand.items()}
        required = {key: _gpus(demand[key], regions[key]["throughput"], regions[key]["utilization"]) for key in regions}
        bad = [key for key in regions if required[key] > regions[key]["capacity"]]
        if bad:
            raise ScenarioError(f"baseline INFEASIBLE at {stamp.isoformat()}: capacity {bad}")
        baseline_required = {f"{r}/{m}": required[(r, m)] for r, m in sorted(regions)}
        perfect_pooling_bound += _perfect_pooling_compute_lower_bound(demand, hour_regions)
        baseline_gpu_hours += sum(required.values())
        fixed_commitment += sum((Decimal(row["committed"]) * row["price"] for row in hour_regions.values()), Decimal(0))
        baseline_variable_usage += sum((Decimal(max(required[k] - hour_regions[k]["committed"], 0)) * hour_regions[k]["overflow_price"] for k in regions), Decimal(0))
        baseline_compute += sum((_invoice(required[k], hour_regions[k]) for k in regions), Decimal(0))
        while True:
            options = []
            for origin, model in sorted(regions):
                source_key = (origin, model)
                source_gpus = required[source_key]
                if source_gpus <= hour_regions[source_key]["committed"] or source_gpus == 0:
                    continue
                local_requests = assigned.get((origin, origin, model), 0)
                hosted_requests = sum(v for (o, d, m), v in assigned.items() if d == origin and m == model)
                lower_capacity = int(Decimal(source_gpus - 1) * regions[source_key]["throughput"] * regions[source_key]["utilization"])
                for dest, dest_model in sorted(regions):
                    route = config["routes"].get((origin, dest, model))
                    if dest == origin or dest_model != model or route is None:
                        continue
                    if route["p95_ms"] > by_hour[stamp][source_key]["max_latency"] or route["ttft_p95_ms"] > by_hour[stamp][source_key]["max_ttft"]:
                        continue
                    dest_key = (dest, model)
                    dest_row = hour_regions[dest_key]
                    dest_hosted = sum(v for (o, d, m), v in assigned.items() if d == dest and m == model)
                    per_dest_gpu = dest_row["throughput"] * dest_row["utilization"]
                    capacity_room = int(Decimal(dest_row["capacity"]) * per_dest_gpu) - dest_hosted
                    paid_room = int(Decimal(min(dest_row["committed"], dest_row["capacity"])) * per_dest_gpu) - dest_hosted
                    for move in sorted({hosted_requests - lower_capacity, local_requests, min(local_requests, capacity_room), min(local_requests, paid_room)}):
                        if move <= 0 or move > local_requests:
                            continue
                        new_source_gpus = _gpus(hosted_requests - move, regions[source_key]["throughput"], regions[source_key]["utilization"])
                        if new_source_gpus >= source_gpus:
                            continue
                        saved_source_compute = _invoice(source_gpus, hour_regions[source_key]) - _invoice(new_source_gpus, hour_regions[source_key])
                        new_dest_gpus = _gpus(dest_hosted + move, dest_row["throughput"], dest_row["utilization"])
                        if new_dest_gpus > regions[dest_key]["capacity"]:
                            continue
                        added_dest_compute = _invoice(new_dest_gpus, hour_regions[dest_key]) - _invoice(required[dest_key], hour_regions[dest_key])
                        added_network = Decimal(move * route["bytes"]) / Decimal(1_000_000_000) * route["egress"]
                        gain = saved_source_compute - added_dest_compute - added_network
                        if gain > 0:
                            options.append((gain, origin, dest, model, move, new_source_gpus, new_dest_gpus, added_network))
            if not options:
                break
            if len(transfers) >= MAX_TRANSFER_STEPS:
                raise ScenarioError(f"solver: exceeded {MAX_TRANSFER_STEPS} transfer steps; no partial report emitted")
            gain, origin, dest, model, move, new_source_gpus, new_dest_gpus, added_network = sorted(options, key=lambda x: (-x[0], x[1], x[2], x[3], x[4]))[0]
            assigned[(origin, origin, model)] -= move
            assigned[(origin, dest, model)] = assigned.get((origin, dest, model), 0) + move
            required[(origin, model)] = new_source_gpus
            required[(dest, model)] = new_dest_gpus
            network += added_network
            transfers.append({"timestamp_utc": stamp.isoformat().replace("+00:00", "Z"), "origin": origin, "destination": dest, "model": model, "requests": move, "network_usd_exact": str(added_network)})
        candidate_variable_usage += sum((Decimal(max(required[k] - hour_regions[k]["committed"], 0)) * hour_regions[k]["overflow_price"] for k in regions), Decimal(0))
        candidate_compute += sum((_invoice(required[k], hour_regions[k]) for k in regions), Decimal(0))
        candidate_gpu_hours += sum(required.values())
        hourly.append({
            "timestamp_utc": stamp.isoformat().replace("+00:00", "Z"),
            "origin_requests": {f"{r}/{m}": demand[(r, m)] for r, m in sorted(regions)},
            "origin_latency_budgets_ms": {
                f"{r}/{m}": {
                    "max_ttft_ms": _exact_decimal(by_hour[stamp][(r, m)]["max_ttft"]),
                    "max_e2e_ms": _exact_decimal(by_hour[stamp][(r, m)]["max_latency"]),
                } for r, m in sorted(regions)
            },
            "baseline_required_gpus": baseline_required,
            "candidate_required_gpus": {f"{r}/{m}": required[(r, m)] for r, m in sorted(regions)},
            "candidate_assignments": [
                {"origin": o, "destination": d, "model": m, "requests": n}
                for (o, d, m), n in sorted(assigned.items()) if n > 0
            ],
        })
    extras = config["extras"]
    added = network + sum(extras.values())
    net = baseline_compute - candidate_compute - added
    displayed_net_before_adjustment = (
        Decimal(_money(baseline_compute)) - Decimal(_money(candidate_compute))
        - Decimal(_money(network)) - Decimal(_money(extras["software_usd"]))
        - Decimal(_money(extras["operations_usd"])) - Decimal(_money(extras["migration_usd"]))
    )
    rounding_adjustment = Decimal(_money(net)) - displayed_net_before_adjustment
    observation_sources = Counter((row["source_kind"], row["source_ref"]) for row in observations)
    return {
        "version": VERSION,
        "input_schema_version": meta["schema_version"],
        "scenario_id": meta["id"],
        "scenario_sha256": scenario_hash,
        "source_kinds": sorted({row["source_kind"] for row in observations} | {region["source_kind"] for region in regions.values()} | {window["source_kind"] for region in regions.values() for window in region["price_windows"]} | {route["source_kind"] for route in config["routes"].values()}),
        "input_provenance": {
            "regions": [
                {"region": r, "model": m, "source_kind": regions[(r, m)]["source_kind"], "source_ref": regions[(r, m)]["source_ref"]}
                for r, m in sorted(regions)
            ],
            "observations": [
                {"source_kind": kind, "source_ref": ref, "rows": observation_sources[(kind, ref)]}
                for kind, ref in sorted(observation_sources)
            ],
            "routes": [
                {"origin": o, "destination": d, "model": m, "source_kind": config["routes"][(o, d, m)]["source_kind"], "source_ref": config["routes"][(o, d, m)]["source_ref"]}
                for o, d, m in sorted(config["routes"])
            ],
        },
        "algorithm": "deterministic_positive_gain_transfer_heuristic",
        "status": "FEASIBLE_HEURISTIC",
        "currency": meta["currency"],
        "period_start_utc": meta["start"].isoformat().replace("+00:00", "Z"),
        "period_end_utc": (meta["start"] + timedelta(hours=meta["hours"])).isoformat().replace("+00:00", "Z"),
        "billing_types": {f"{r}/{m}": regions[(r, m)]["billing_type"] for r, m in sorted(regions)},
        "route_latency_terms": [
            {"origin": o, "destination": d, "model": m,
             "estimated_ttft_p95_ms": str(config["routes"][(o, d, m)]["ttft_p95_ms"]),
             "estimated_e2e_p95_ms": str(config["routes"][(o, d, m)]["p95_ms"])}
            for o, d, m in sorted(config["routes"])
        ],
        "billing_terms": {
            f"{r}/{m}": {
                "fixed_committed_gpus": regions[(r, m)]["committed"] if regions[(r, m)]["billing_type"] == "noncancellable_reservation" else 0,
                "owned_capacity_gpus": regions[(r, m)]["owned"] if regions[(r, m)]["billing_type"] == "owned" else None,
                "fixed_rate_usd_gpu_hour": str(regions[(r, m)]["price"]) if regions[(r, m)]["billing_type"] == "noncancellable_reservation" else None,
                "overflow_rate_usd_gpu_hour": str(regions[(r, m)]["overflow_price"]) if regions[(r, m)]["billing_type"] != "owned" and not regions[(r, m)]["price_windows"] else None,
                "on_demand_price_windows": [
                    {"start_utc": window["start"].isoformat().replace("+00:00", "Z"),
                     "end_utc": window["end"].isoformat().replace("+00:00", "Z"),
                     "price_usd_gpu_hour": _exact_decimal(window["price"]),
                     "source_kind": window["source_kind"], "source_ref": window["source_ref"]}
                    for window in regions[(r, m)]["price_windows"]
                ] if regions[(r, m)]["price_windows"] else None,
                "owned_cash_basis": "GPU purchase/depreciation excluded; supply incremental power/operations separately" if regions[(r, m)]["billing_type"] == "owned" else None,
                "reservation_region": regions[(r, m)]["reservation_region"],
                "reservation_start_utc": regions[(r, m)]["reservation_start"].isoformat().replace("+00:00", "Z") if regions[(r, m)]["reservation_start"] else None,
                "reservation_end_utc": regions[(r, m)]["reservation_end"].isoformat().replace("+00:00", "Z") if regions[(r, m)]["reservation_end"] else None,
                "synthetic_reservation_terms_assumed": regions[(r, m)]["reservation_terms_assumed"],
                "on_demand_price_start_utc": regions[(r, m)]["price_start"].isoformat().replace("+00:00", "Z") if regions[(r, m)]["price_start"] else None,
                "on_demand_price_end_utc": regions[(r, m)]["price_end"].isoformat().replace("+00:00", "Z") if regions[(r, m)]["price_end"] else None,
                "synthetic_price_window_assumed": regions[(r, m)]["price_window_assumed"],
            } for r, m in sorted(regions)
        },
        "hours": meta["hours"],
        "baseline_compute_usd": _money(baseline_compute),
        "candidate_compute_usd": _money(candidate_compute),
        "billing_breakdown_usd_exact": {
            "fixed_commitment": _exact_decimal(fixed_commitment),
            "baseline_variable_usage": _exact_decimal(baseline_variable_usage),
            "candidate_variable_usage": _exact_decimal(candidate_variable_usage),
        },
        "perfect_pooling_compute_lower_bound_usd": str(perfect_pooling_bound.quantize(Decimal("0.01"), rounding=ROUND_FLOOR)),
        "perfect_pooling_bound_scope": "Compute invoice lower bound only: ignore routes, latency, residency, network and software costs; allow fractional incremental GPUs while retaining fixed noncancellable charges.",
        "baseline_required_gpu_hours": baseline_gpu_hours,
        "candidate_required_gpu_hours": candidate_gpu_hours,
        "theoretical_gpu_hours_reduction": baseline_gpu_hours - candidate_gpu_hours,
        "network_usd": _money(network),
        "software_usd": _money(extras["software_usd"]),
        "operations_usd": _money(extras["operations_usd"]),
        "migration_usd": _money(extras["migration_usd"]),
        "rounding_adjustment_usd": _money(rounding_adjustment),
        "net_current_cash_delta_usd": _money(net),
        "transfers": transfers,
        "hourly": hourly,
        "limitations": [
            "Synthetic or supplied throughput and route TTFT/end-to-end p95 estimates are not measured SLA or p99 guarantees unless explicitly sourced.",
            "Route eligibility checks both estimated TTFT p95 and end-to-end p95 against each origin-hour budget; cache, queuing and tail behavior still require independent measurement.",
            "Fixed reservations are scoped to one region/model for the full scenario; mid-period cancellation and globally fungible commitments are unsupported.",
            "Owned GPUs have no current GPU rental invoice in this model; hardware purchase/depreciation and future procurement avoidance are excluded, while incremental power/operations must be supplied separately.",
            "Synthetic reservation terms omitted from input assume the same fixed and overflow rate and the scenario's region/window.",
            "Synthetic flat on-demand prices without explicit UTC dates assume validity over the scenario window; scheduled prices use explicit contiguous UTC windows.",
            "The perfect-pooling bound is a fractional compute-only relaxation, not a feasible route plan or net cash forecast.",
            "Candidate is feasible but not proven globally optimal.",
            "This report does not establish a customer invoice saving without contract evidence.",
        ],
    }


CSV_OBSERVATION_FIELDS = (
    "scenario_id", "timestamp_utc", "origin_region", "model_id", "requests",
    "mean_input_tokens", "mean_output_tokens", "max_ttft_ms",
    "max_e2e_ms", "source_kind", "source_ref",
)


def parse_observations_csv(text: str) -> list[dict[str, Any]]:
    """Parse explicit hourly aggregates without filling gaps or guessing units."""
    try:
        reader = csv.DictReader(StringIO(text, newline=""), strict=True)
        if reader.fieldnames is None or tuple(reader.fieldnames) != CSV_OBSERVATION_FIELDS:
            raise ScenarioError("CSV header: expected canonical observation columns in order")
        rows = []
        for line_number, row in enumerate(reader, start=2):
            if line_number > 8 * 24 * 31 + 1:
                raise ScenarioError("CSV: too many observation rows")
            if None in row or any(value is None for value in row.values()):
                raise ScenarioError(f"CSV line {line_number}: wrong column count")
            requests = row["requests"].strip()
            if not requests.isdecimal() or any(ch not in "0123456789" for ch in requests):
                raise ScenarioError(f"CSV line {line_number}: requests must be a nonnegative integer")
            row["requests"] = int(requests)
            rows.append(row)
        return rows
    except csv.Error as exc:
        raise ScenarioError(f"CSV parse error: {exc}") from exc


def _safe_csv_text(value: Any) -> str:
    """Prevent user-controlled text from becoming a spreadsheet formula."""
    result = str(value)
    if result.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + result
    return result


def render_report_csv(report: dict[str, Any]) -> str:
    """Export the cost waterfall and candidate assignments in one CSV."""
    columns = (
        "record_type", "scenario_id", "scenario_sha256", "version", "status",
        "currency", "exported_utc", "timestamp_utc", "origin", "destination", "model",
        "requests", "metric", "value", "source_kinds", "limitations",
        "window_end_utc", "source_kind", "source_ref",
    )
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    common = {
        "scenario_id": _safe_csv_text(report["scenario_id"]),
        "scenario_sha256": report["scenario_sha256"],
        "version": report["version"],
        "status": report["status"],
        "currency": report["currency"],
        "exported_utc": report.get("exported_utc", ""),
        "source_kinds": _safe_csv_text(";".join(report["source_kinds"])),
        "limitations": _safe_csv_text(";".join(report["limitations"])),
    }
    for metric in (
        "baseline_compute_usd", "candidate_compute_usd", "perfect_pooling_compute_lower_bound_usd", "network_usd",
        "software_usd", "operations_usd", "migration_usd", "rounding_adjustment_usd",
        "net_current_cash_delta_usd", "baseline_required_gpu_hours",
        "candidate_required_gpu_hours", "theoretical_gpu_hours_reduction",
    ):
        writer.writerow({**common, "record_type": "cost", "metric": metric, "value": report[metric]})
    for metric, value in report["billing_breakdown_usd_exact"].items():
        writer.writerow({**common, "record_type": "cost", "metric": metric + "_usd_exact", "value": value})
    for metric in ("input_schema_version", "period_start_utc", "period_end_utc"):
        writer.writerow({**common, "record_type": "metadata", "metric": metric, "value": report[metric]})
    for record in report["input_provenance"]["regions"]:
        region, model = record["region"], record["model"]
        for metric, value in report["billing_terms"][f"{region}/{model}"].items():
            if metric == "on_demand_price_windows":
                for window in value or []:
                    writer.writerow({
                        **common, "record_type": "on_demand_price_window",
                        "timestamp_utc": window["start_utc"], "window_end_utc": window["end_utc"],
                        "origin": _safe_csv_text(region), "model": _safe_csv_text(model),
                        "metric": "price_usd_gpu_hour", "value": window["price_usd_gpu_hour"],
                        "source_kind": window["source_kind"], "source_ref": _safe_csv_text(window["source_ref"]),
                    })
            elif value is not None:
                writer.writerow({
                    **common, "record_type": "billing_term",
                    "origin": _safe_csv_text(region), "model": _safe_csv_text(model),
                    "metric": metric, "value": _safe_csv_text(value),
                })
    for route in report["route_latency_terms"]:
        for metric in ("estimated_ttft_p95_ms", "estimated_e2e_p95_ms"):
            writer.writerow({
                **common, "record_type": "route_latency_term",
                "origin": _safe_csv_text(route["origin"]),
                "destination": _safe_csv_text(route["destination"]),
                "model": _safe_csv_text(route["model"]),
                "metric": metric, "value": route[metric],
            })
    for hour in report["hourly"]:
        for source in report["input_provenance"]["regions"]:
            region, model = source["region"], source["model"]
            budgets = hour["origin_latency_budgets_ms"][f"{region}/{model}"]
            for metric, value in budgets.items():
                writer.writerow({
                    **common, "record_type": "origin_hour_budget",
                    "timestamp_utc": hour["timestamp_utc"],
                    "origin": _safe_csv_text(region), "model": _safe_csv_text(model),
                    "metric": metric, "value": value,
                })
        for assignment in hour["candidate_assignments"]:
            writer.writerow({
                **common, "record_type": "assignment",
                "timestamp_utc": hour["timestamp_utc"],
                "origin": _safe_csv_text(assignment["origin"]),
                "destination": _safe_csv_text(assignment["destination"]),
                "model": _safe_csv_text(assignment["model"]),
                "requests": assignment["requests"],
            })
    for transfer in report["transfers"]:
        writer.writerow({
            **common, "record_type": "transfer",
            "timestamp_utc": transfer["timestamp_utc"],
            "origin": _safe_csv_text(transfer["origin"]),
            "destination": _safe_csv_text(transfer["destination"]),
            "model": _safe_csv_text(transfer["model"]),
            "requests": transfer["requests"],
            "metric": "network_usd_exact", "value": transfer["network_usd_exact"],
        })
    for group, records in report["input_provenance"].items():
        for record in records:
            writer.writerow({
                **common, "record_type": "provenance", "metric": group,
                "origin": _safe_csv_text(record.get("region", record.get("origin", ""))),
                "destination": _safe_csv_text(record.get("destination", "")),
                "model": _safe_csv_text(record.get("model", "")),
                "requests": record.get("rows", ""),
                "value": _safe_csv_text(record["source_kind"] + ":" + record["source_ref"]),
            })
    return output.getvalue()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--observations-csv", type=Path, help="canonical hourly CSV; scenario JSON must omit observations")
    parser.add_argument("--report-csv", type=Path, help="optional cost and assignment CSV export")
    args = parser.parse_args()
    sources = [args.scenario] + ([args.observations_csv] if args.observations_csv else [])
    outputs = [args.report] + ([args.report_csv] if args.report_csv else [])
    if len({p.resolve() for p in sources + outputs}) != len(sources + outputs):
        parser.error("input and output paths must be distinct")
    if args.scenario.stat().st_size > 10_000_000:
        parser.error("scenario JSON exceeds 10 MB")
    raw = parse_json_strict(args.scenario.read_text(encoding="utf-8"))
    if args.observations_csv:
        if "observations" in raw:
            parser.error("scenario JSON must omit observations when --observations-csv is used")
        if args.observations_csv.stat().st_size > 10_000_000:
            parser.error("observations CSV exceeds 10 MB")
        raw["observations"] = parse_observations_csv(args.observations_csv.read_text(encoding="utf-8-sig"))
    report = run_scenario(raw)
    report["exported_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.report_csv:
        args.report_csv.write_text(render_report_csv(report), encoding="utf-8")


if __name__ == "__main__":
    main()
