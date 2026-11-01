"""Independent reference and invariant checks for the offline prototype."""

from __future__ import annotations

import copy
import csv
import random
import sys
import unittest
from itertools import product
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sw004_simulator import CSV_OBSERVATION_FIELDS, ScenarioError, parse_json_strict, parse_observations_csv, render_report_csv, run_scenario


def scenario(hours: int = 1, region_count: int = 2) -> dict:
    names = ["US", "EU", "ASIA"][:region_count]
    start = datetime(2026, 10, 26, tzinfo=timezone.utc)
    regions = []
    observations = []
    for name in names:
        regions.append({
            "region": name,
            "model": "m1",
            "capacity_gpus": 4,
            "reserve_gpus": 0,
            "committed_gpus": 0,
            "billing_type": "on_demand",
            "requests_per_gpu_hour": 60,
            "max_utilization": "0.8",
            "price_usd_gpu_hour": "3.99",
            "source_kind": "synthetic",
            "source_ref": "fixture",
        })
    for h in range(hours):
        for name in names:
            observations.append({
                "scenario_id": "fixture",
                "timestamp_utc": (start + timedelta(hours=h)).isoformat().replace("+00:00", "Z"),
                "origin_region": name,
                "model_id": "m1",
                "requests": 100 if name == "US" else 0,
                "mean_input_tokens": 100,
                "mean_output_tokens": 50,
                "max_ttft_ms": 100,
                "max_e2e_ms": 400,
                "source_kind": "synthetic",
                "source_ref": "fixture",
            })
    return {
        "schema_version": 1,
        "scenario_id": "fixture",
        "currency": "USD",
        "start_utc": start.isoformat().replace("+00:00", "Z"),
        "hours": hours,
        "regions": regions,
        "observations": observations,
        "allowed_routes": [],
    }


def route() -> dict:
    return {
        "origin": "US", "destination": "EU", "model": "m1",
        "residency_permission": True, "estimated_p95_ms": 200, "estimated_ttft_p95_ms": 80,
        "bytes_per_request": 1000, "egress_usd_gb": "0.10",
        "source_kind": "synthetic", "source_ref": "fixture_route",
    }


class SimulatorTests(unittest.TestCase):
    def test_json_parser_rejects_duplicate_nested_fields_and_nonstandard_numbers(self):
        with self.assertRaisesRegex(ScenarioError, "duplicate field 'requests'"):
            parse_json_strict('{"observations":[{"requests":1,"requests":2}]}')
        with self.assertRaisesRegex(ScenarioError, "nonstandard number 'NaN'"):
            parse_json_strict('{"price":NaN}')
        with self.assertRaisesRegex(ScenarioError, "nesting exceeds parser limit"):
            parse_json_strict("[" * 10_000 + "0" + "]" * 10_000)

    def test_hourly_on_demand_price_windows_change_invoice_and_route_gain(self):
        case = scenario(hours=2)
        source = case["regions"][0]
        source.pop("price_usd_gpu_hour")
        source["source_kind"] = "operator_supplied"
        source["source_ref"] = "capacity_record"
        source["on_demand_price_windows"] = [
            {"start_utc": "2026-10-26T00:00:00Z", "end_utc": "2026-10-26T01:00:00Z", "price_usd_gpu_hour": "0.5", "source_kind": "operator_supplied", "source_ref": "rate_1"},
            {"start_utc": "2026-10-26T01:00:00Z", "end_utc": "2026-10-26T02:00:00Z", "price_usd_gpu_hour": "4", "source_kind": "operator_supplied", "source_ref": "rate_2"},
        ]
        case["regions"][1]["price_usd_gpu_hour"] = "1"
        edge = route()
        edge["bytes_per_request"] = 0
        case["allowed_routes"] = [edge]
        report = run_scenario(case)
        self.assertEqual(report["input_schema_version"], 1)
        self.assertEqual((report["baseline_compute_usd"], report["candidate_compute_usd"], report["net_current_cash_delta_usd"]), ("13.50", "4.50", "9.00"))
        self.assertEqual([t["timestamp_utc"] for t in report["transfers"]], ["2026-10-26T01:00:00Z"])
        self.assertEqual([w["price_usd_gpu_hour"] for w in report["billing_terms"]["US/m1"]["on_demand_price_windows"]], ["0.5", "4"])
        exported = list(csv.DictReader(StringIO(render_report_csv(report))))
        windows = [row for row in exported if row["record_type"] == "on_demand_price_window"]
        self.assertTrue(any(row["record_type"] == "metadata" and row["metric"] == "input_schema_version" and row["value"] == "1" for row in exported))
        self.assertEqual([(w["timestamp_utc"], w["window_end_utc"], w["value"], w["source_ref"]) for w in windows], [
            ("2026-10-26T00:00:00Z", "2026-10-26T01:00:00Z", "0.5", "rate_1"),
            ("2026-10-26T01:00:00Z", "2026-10-26T02:00:00Z", "4", "rate_2"),
        ])
        source["on_demand_price_windows"][1]["start_utc"] = "2026-10-26T02:00:00Z"
        with self.assertRaisesRegex(ScenarioError, "contiguous"):
            run_scenario(case)
        source["on_demand_price_windows"][1]["start_utc"] = "2026-10-26T01:00:00Z"
        source["price_usd_gpu_hour"] = "3"
        with self.assertRaisesRegex(ScenarioError, "cannot mix"):
            run_scenario(case)

    def test_owned_capacity_excludes_sunk_gpu_cost_but_can_avoid_rental(self):
        case = scenario()
        owned = case["regions"][1]
        owned.pop("committed_gpus")
        owned.update(billing_type="owned", owned_gpus=4, price_usd_gpu_hour="0")
        edge = route()
        edge["bytes_per_request"] = 0
        case["allowed_routes"] = [edge]
        report = run_scenario(case)
        self.assertEqual(report["baseline_compute_usd"], "11.97")
        self.assertEqual(report["candidate_compute_usd"], "0.00")
        self.assertEqual(report["net_current_cash_delta_usd"], "11.97")
        self.assertEqual(report["billing_terms"]["EU/m1"]["owned_capacity_gpus"], 4)
        self.assertEqual(report["billing_terms"]["EU/m1"]["fixed_committed_gpus"], 0)
        exported = list(csv.DictReader(StringIO(render_report_csv(report))))
        self.assertTrue(any(row["record_type"] == "billing_term" and row["metric"] == "owned_capacity_gpus" and row["value"] == "4" for row in exported))
        case["regions"][0].pop("committed_gpus")
        case["regions"][0].update(billing_type="owned", owned_gpus=4, price_usd_gpu_hour="0")
        report = run_scenario(case)
        self.assertEqual(report["net_current_cash_delta_usd"], "0.00")
        self.assertFalse(report["transfers"])

    def test_owned_capacity_rejects_rental_or_mixed_terms(self):
        case = scenario()
        owned = case["regions"][1]
        owned.pop("committed_gpus")
        owned.update(billing_type="owned", owned_gpus=4, price_usd_gpu_hour="1")
        with self.assertRaisesRegex(ScenarioError, "zero current GPU invoice rate"):
            run_scenario(case)
        owned["price_usd_gpu_hour"] = "0"
        owned["overflow_price_usd_gpu_hour"] = "1"
        with self.assertRaisesRegex(ScenarioError, "cannot contain rental or reservation terms"):
            run_scenario(case)
        owned.pop("overflow_price_usd_gpu_hour")
        owned["committed_gpus"] = 0
        with self.assertRaisesRegex(ScenarioError, "cannot contain committed_gpus"):
            run_scenario(case)
        owned.pop("committed_gpus")
        owned["owned_gpus"] = 3
        with self.assertRaisesRegex(ScenarioError, "must equal positive capacity_gpus"):
            run_scenario(case)

    def test_route_ttft_budget_is_enforced_and_exported(self):
        case = scenario()
        case["regions"][1]["price_usd_gpu_hour"] = "0.50"
        edge = route()
        case["allowed_routes"] = [edge]
        report = run_scenario(case)
        self.assertTrue(report["transfers"])
        self.assertEqual(report["route_latency_terms"][0]["estimated_ttft_p95_ms"], "80")
        self.assertEqual(report["hourly"][0]["origin_latency_budgets_ms"]["US/m1"], {"max_ttft_ms": "100", "max_e2e_ms": "400"})
        exported = list(csv.DictReader(StringIO(render_report_csv(report))))
        self.assertTrue(any(row["record_type"] == "route_latency_term" and row["metric"] == "estimated_ttft_p95_ms" and row["value"] == "80" for row in exported))
        self.assertTrue(any(row["record_type"] == "origin_hour_budget" and row["timestamp_utc"] == case["start_utc"] and row["origin"] == "US" and row["model"] == "m1" and row["metric"] == "max_ttft_ms" and row["value"] == "100" for row in exported))
        edge["estimated_ttft_p95_ms"] = 120
        self.assertFalse(run_scenario(case)["transfers"])
        del edge["estimated_ttft_p95_ms"]
        with self.assertRaisesRegex(ScenarioError, "estimated_ttft_p95_ms"):
            run_scenario(case)
        edge["estimated_ttft_p95_ms"] = 220
        with self.assertRaisesRegex(ScenarioError, "TTFT p95 exceeds end-to-end p95"):
            run_scenario(case)

    def test_actual_on_demand_price_requires_covering_utc_window(self):
        case = scenario()
        source = case["regions"][0]
        source["source_kind"] = "operator_supplied"
        with self.assertRaisesRegex(ScenarioError, "actual on-demand price requires explicit UTC window"):
            run_scenario(case)
        source["price_start_utc"] = case["start_utc"]
        with self.assertRaisesRegex(ScenarioError, "price dates must both be supplied"):
            run_scenario(case)
        source["price_end_utc"] = case["start_utc"]
        with self.assertRaisesRegex(ScenarioError, "price window does not cover"):
            run_scenario(case)
        source["price_end_utc"] = "2026-10-26T01:00:00Z"
        result = run_scenario(case)
        terms = result["billing_terms"]["US/m1"]
        self.assertEqual(terms["on_demand_price_start_utc"], case["start_utc"])
        self.assertFalse(terms["synthetic_price_window_assumed"])
        exported = list(csv.DictReader(StringIO(render_report_csv(result))))
        self.assertTrue(any(row["record_type"] == "billing_term" and row["origin"] == "US" and row["metric"] == "on_demand_price_end_utc" and row["value"] == source["price_end_utc"] for row in exported))
        self.assertTrue(any(row["record_type"] == "metadata" and row["metric"] == "period_end_utc" and row["value"] == source["price_end_utc"] for row in exported))
        self.assertTrue(run_scenario(scenario())["billing_terms"]["US/m1"]["synthetic_price_window_assumed"])

    def test_region_model_report_key_collision_is_rejected(self):
        case = scenario()
        case["regions"][0].update(region="US/a", model="b")
        case["regions"][1].update(region="US", model="a/b")
        with self.assertRaisesRegex(ScenarioError, "ambiguous region/model report key"):
            run_scenario(case)

    def test_large_paid_commitment_fills_in_one_transfer(self):
        case = scenario()
        source, destination = case["regions"]
        source.update(capacity_gpus=10_000, requests_per_gpu_hour=1, max_utilization="1", price_usd_gpu_hour="1")
        destination.update(
            capacity_gpus=5_000, committed_gpus=5_000,
            billing_type="noncancellable_reservation", requests_per_gpu_hour=1,
            max_utilization="1", price_usd_gpu_hour="0",
            overflow_price_usd_gpu_hour="100", reservation_region="EU",
            reservation_start_utc=case["start_utc"],
            reservation_end_utc="2026-10-26T01:00:00Z",
        )
        case["observations"][0]["requests"] = 10_000
        edge = route()
        edge["bytes_per_request"] = 0
        case["allowed_routes"] = [edge]
        result = run_scenario(case)
        self.assertEqual(result["baseline_compute_usd"], "10000.00")
        self.assertEqual(result["candidate_compute_usd"], "5000.00")
        self.assertEqual([transfer["requests"] for transfer in result["transfers"]], [5_000])
        with patch("sw004_simulator.MAX_TRANSFER_STEPS", 0):
            with self.assertRaisesRegex(ScenarioError, "no partial report emitted"):
                run_scenario(case)

    def test_unsupported_contract_and_scenario_fields_fail_closed(self):
        case = scenario()
        case["regions"][0]["cancellation_effective_utc"] = "2026-10-26T00:00:00Z"
        with self.assertRaisesRegex(ScenarioError, "regions\\[0\\]: unsupported field 'cancellation_effective_utc'"):
            run_scenario(case)
        del case["regions"][0]["cancellation_effective_utc"]
        case["schema_version"] = 2
        with self.assertRaisesRegex(ScenarioError, "schema_version: expected integer 1"):
            run_scenario(case)
        case["schema_version"] = True
        with self.assertRaisesRegex(ScenarioError, "schema_version: expected integer 1"):
            run_scenario(case)
        del case["schema_version"]
        with self.assertRaisesRegex(ScenarioError, "schema_version: expected integer 1"):
            run_scenario(case)
        case["schema_version"] = 1
        case["observations"][0]["customer_id"] = "should-not-be-in-aggregate"
        with self.assertRaisesRegex(ScenarioError, "observations\\[0\\]: unsupported field 'customer_id'"):
            run_scenario(case)
        del case["observations"][0]["customer_id"]
        case["allowed_routes"] = [route()]
        case["allowed_routes"][0]["unapproved_region_pair"] = True
        with self.assertRaisesRegex(ScenarioError, "allowed_routes\\[0\\]: unsupported field 'unapproved_region_pair'"):
            run_scenario(case)

    def test_distinct_reservation_and_overflow_rates_change_route_gain(self):
        case = scenario()
        source = case["regions"][0]
        source.update(
            committed_gpus=2,
            billing_type="noncancellable_reservation",
            price_usd_gpu_hour="1",
            overflow_price_usd_gpu_hour="10",
            reservation_region="US",
            reservation_start_utc=case["start_utc"],
            reservation_end_utc="2026-10-26T01:00:00Z",
        )
        case["regions"][1]["price_usd_gpu_hour"] = "2"
        edge = route()
        edge["bytes_per_request"] = 0
        case["allowed_routes"] = [edge]
        result = run_scenario(case)
        self.assertEqual(result["baseline_compute_usd"], "12.00")
        self.assertEqual(result["candidate_compute_usd"], "4.00")
        self.assertEqual(result["net_current_cash_delta_usd"], "8.00")
        breakdown = result["billing_breakdown_usd_exact"]
        self.assertEqual(breakdown, {
            "fixed_commitment": "2",
            "baseline_variable_usage": "10",
            "candidate_variable_usage": "2",
        })
        self.assertEqual(
            Decimal(breakdown["fixed_commitment"]) + Decimal(breakdown["baseline_variable_usage"]),
            Decimal(result["baseline_compute_usd"]),
        )
        csv_metrics = {row["metric"]: row["value"] for row in csv.DictReader(StringIO(render_report_csv(result)))}
        self.assertEqual(csv_metrics["fixed_commitment_usd_exact"], "2")
        self.assertEqual(csv_metrics["candidate_variable_usage_usd_exact"], "2")
        self.assertEqual(result["transfers"][0]["requests"], 4)
        self.assertEqual(result["billing_terms"]["US/m1"]["overflow_rate_usd_gpu_hour"], "10")
        self.assertLessEqual(
            Decimal(result["perfect_pooling_compute_lower_bound_usd"]),
            Decimal(result["candidate_compute_usd"]),
        )

    def test_actual_reservation_requires_explicit_rate_region_and_window(self):
        case = scenario()
        source = case["regions"][0]
        source.update(committed_gpus=2, billing_type="noncancellable_reservation", source_kind="operator_supplied")
        with self.assertRaisesRegex(ScenarioError, "explicit overflow rate"):
            run_scenario(case)
        source.update(
            overflow_price_usd_gpu_hour="4.25",
            reservation_region="EU",
            reservation_start_utc=case["start_utc"],
            reservation_end_utc="2026-10-26T01:00:00Z",
        )
        with self.assertRaisesRegex(ScenarioError, "reservation region/window"):
            run_scenario(case)
        source["reservation_region"] = "US"
        source["reservation_end_utc"] = case["start_utc"]
        with self.assertRaisesRegex(ScenarioError, "reservation region/window"):
            run_scenario(case)
        source["reservation_end_utc"] = "2026-10-26T01:00:00Z"
        self.assertFalse(run_scenario(case)["billing_terms"]["US/m1"]["synthetic_reservation_terms_assumed"])

    def test_partial_synthetic_reservation_terms_are_rejected(self):
        case = scenario()
        case["regions"][0].update(
            committed_gpus=2,
            billing_type="noncancellable_reservation",
            overflow_price_usd_gpu_hour="10",
        )
        with self.assertRaisesRegex(ScenarioError, "all supplied or all omitted"):
            run_scenario(case)

    def test_displayed_cash_waterfall_reconciles_at_subcent_rates(self):
        case = scenario()
        case["observations"][0]["requests"] = 1
        case["regions"][0].update(capacity_gpus=1, requests_per_gpu_hour=1, max_utilization="1", price_usd_gpu_hour="0.006")
        case["regions"][1].update(capacity_gpus=1, requests_per_gpu_hour=1, max_utilization="1", price_usd_gpu_hour="0.004")
        allowed = route()
        allowed["bytes_per_request"] = 0
        case["allowed_routes"] = [allowed]
        result = run_scenario(case)
        self.assertEqual(result["baseline_compute_usd"], "0.01")
        self.assertEqual(result["candidate_compute_usd"], "0.00")
        self.assertEqual(result["net_current_cash_delta_usd"], "0.00")
        self.assertEqual(result["rounding_adjustment_usd"], "-0.01")
        self.assertEqual(result["billing_breakdown_usd_exact"], {
            "fixed_commitment": "0",
            "baseline_variable_usage": "0.006",
            "candidate_variable_usage": "0.004",
        })
        shown = Decimal(result["baseline_compute_usd"]) - sum(
            Decimal(result[field]) for field in (
                "candidate_compute_usd", "network_usd", "software_usd",
                "operations_usd", "migration_usd"
            )
        ) + Decimal(result["rounding_adjustment_usd"])
        self.assertEqual(shown, Decimal(result["net_current_cash_delta_usd"]))
        csv_metrics = {
            row["metric"]: row["value"] for row in csv.DictReader(StringIO(render_report_csv(result)))
            if row["record_type"] == "cost"
        }
        self.assertEqual(csv_metrics["rounding_adjustment_usd"], "-0.01")

    def test_whole_gpu_reference_and_explicit_zero(self):
        result = run_scenario(scenario())
        self.assertEqual(result["baseline_compute_usd"], "11.97")
        self.assertEqual(result["perfect_pooling_compute_lower_bound_usd"], "8.31")
        self.assertEqual(result["hourly"][0]["baseline_required_gpus"], {"EU/m1": 0, "US/m1": 3})
        self.assertEqual(result["net_current_cash_delta_usd"], "0.00")

    def test_perfect_pooling_bound_retains_fixed_commitment_and_ignores_routes(self):
        case = scenario()
        case["regions"][1]["committed_gpus"] = 3
        case["regions"][1]["billing_type"] = "noncancellable_reservation"
        result = run_scenario(case)
        self.assertEqual(result["perfect_pooling_compute_lower_bound_usd"], "11.97")
        self.assertEqual(result["candidate_compute_usd"], "23.94")
        self.assertFalse(result["transfers"])
        self.assertEqual(result["theoretical_gpu_hours_reduction"], 0)

    def test_pooling_bound_below_enumerated_integer_optimum(self):
        rng = random.Random(42004)
        for _ in range(60):
            case = scenario()
            for region, observation in zip(case["regions"], case["observations"]):
                region["capacity_gpus"] = rng.randrange(1, 4)
                region["requests_per_gpu_hour"] = rng.randrange(3, 11)
                region["max_utilization"] = "1"
                region["price_usd_gpu_hour"] = str(Decimal(rng.randrange(1, 501)) / 100)
                region["committed_gpus"] = rng.randrange(region["capacity_gpus"] + 1)
                region["billing_type"] = "noncancellable_reservation" if region["committed_gpus"] else "on_demand"
                if region["committed_gpus"]:
                    region.update(
                        overflow_price_usd_gpu_hour=str(Decimal(rng.randrange(1, 1001)) / 100),
                        reservation_region=region["region"],
                        reservation_start_utc=case["start_utc"],
                        reservation_end_utc="2026-10-26T01:00:00Z",
                    )
                observation["requests"] = rng.randrange(region["capacity_gpus"] * region["requests_per_gpu_hour"] + 1)
            demand = sum(row["requests"] for row in case["observations"])
            a, b = case["regions"]
            exact_integer_minimum = min(
                Decimal(a["committed_gpus"]) * Decimal(a["price_usd_gpu_hour"])
                + Decimal(max(x - a["committed_gpus"], 0)) * Decimal(a.get("overflow_price_usd_gpu_hour", a["price_usd_gpu_hour"]))
                + Decimal(b["committed_gpus"]) * Decimal(b["price_usd_gpu_hour"])
                + Decimal(max(y - b["committed_gpus"], 0)) * Decimal(b.get("overflow_price_usd_gpu_hour", b["price_usd_gpu_hour"]))
                for x in range(a["capacity_gpus"] + 1)
                for y in range(b["capacity_gpus"] + 1)
                if x * a["requests_per_gpu_hour"] + y * b["requests_per_gpu_hour"] >= demand
            )
            report = run_scenario(case)
            self.assertLessEqual(Decimal(report["perfect_pooling_compute_lower_bound_usd"]), exact_integer_minimum)

    def test_three_region_bound_below_independent_integer_enumeration(self):
        rng = random.Random(870041)
        for _ in range(150):
            case = scenario(region_count=3)
            for region, observation in zip(case["regions"], case["observations"]):
                region["capacity_gpus"] = rng.randrange(1, 4)
                region["requests_per_gpu_hour"] = rng.randrange(3, 11)
                region["max_utilization"] = "1"
                region["price_usd_gpu_hour"] = str(Decimal(rng.randrange(1, 501)) / 100)
                region["committed_gpus"] = rng.randrange(region["capacity_gpus"] + 1)
                region["billing_type"] = "noncancellable_reservation" if region["committed_gpus"] else "on_demand"
                if region["committed_gpus"]:
                    region.update(
                        overflow_price_usd_gpu_hour=str(Decimal(rng.randrange(1, 1001)) / 100),
                        reservation_region=region["region"],
                        reservation_start_utc=case["start_utc"],
                        reservation_end_utc="2026-10-26T01:00:00Z",
                    )
                observation["requests"] = rng.randrange(region["capacity_gpus"] * region["requests_per_gpu_hour"] + 1)
            demand = sum(row["requests"] for row in case["observations"])
            rows = case["regions"]
            exact_integer_minimum = min(
                sum((
                    Decimal(row["committed_gpus"]) * Decimal(row["price_usd_gpu_hour"])
                    + Decimal(max(count - row["committed_gpus"], 0))
                    * Decimal(row.get("overflow_price_usd_gpu_hour", row["price_usd_gpu_hour"]))
                    for count, row in zip(counts, rows)
                ), Decimal(0))
                for counts in product(*(range(row["capacity_gpus"] + 1) for row in rows))
                if sum(count * row["requests_per_gpu_hour"] for count, row in zip(counts, rows)) >= demand
            )
            report = run_scenario(case)
            bound = Decimal(report["perfect_pooling_compute_lower_bound_usd"])
            self.assertLessEqual(bound, exact_integer_minimum)
            self.assertLessEqual(bound, Decimal(report["candidate_compute_usd"]))

    def test_fractional_bound_does_not_lose_cent_on_exact_integer(self):
        case = scenario()
        source, destination = case["regions"]
        source.update(capacity_gpus=4, requests_per_gpu_hour=2, max_utilization="1", price_usd_gpu_hour="3")
        destination.update(capacity_gpus=3, requests_per_gpu_hour=3, max_utilization="1", price_usd_gpu_hour="4")
        case["observations"][0]["requests"] = 6
        edge = route()
        edge["bytes_per_request"] = 0
        case["allowed_routes"] = [edge]
        report = run_scenario(case)
        # Independent feasible plan: place all six requests on two destination GPUs at $4 each.
        self.assertEqual(report["perfect_pooling_compute_lower_bound_usd"], "8.00")
        self.assertEqual(report["candidate_compute_usd"], "8.00")
        self.assertEqual(report["transfers"][0]["requests"], 6)

    def test_explicit_allowlist_and_capacity(self):
        case = scenario()
        case["regions"][1]["committed_gpus"] = 3
        case["regions"][1]["billing_type"] = "noncancellable_reservation"
        case["allowed_routes"] = [route()]
        result = run_scenario(case)
        self.assertTrue(result["transfers"])
        self.assertEqual(sum(t["requests"] for t in result["transfers"]), 100)
        self.assertEqual(result["candidate_compute_usd"], "11.97")
        self.assertEqual(result["hourly"][0]["candidate_required_gpus"], {"EU/m1": 3, "US/m1": 0})
        self.assertTrue(all(t["origin"] == "US" and t["destination"] == "EU" for t in result["transfers"]))

    def test_reverse_edge_does_not_authorize_transfer(self):
        case = scenario()
        case["regions"][1]["committed_gpus"] = 3
        case["regions"][1]["billing_type"] = "noncancellable_reservation"
        edge = route()
        edge["origin"], edge["destination"] = edge["destination"], edge["origin"]
        case["allowed_routes"] = [edge]
        self.assertFalse(run_scenario(case)["transfers"])

    def test_strict_latency_prevents_remote_route(self):
        case = scenario()
        case["regions"][1]["committed_gpus"] = 3
        case["regions"][1]["billing_type"] = "noncancellable_reservation"
        case["allowed_routes"] = [route()]
        case["observations"][0]["max_e2e_ms"] = 100
        self.assertFalse(run_scenario(case)["transfers"])

    def test_commitment_has_no_current_compute_cash_saving(self):
        case = scenario()
        case["regions"][0]["committed_gpus"] = 3
        case["regions"][0]["billing_type"] = "noncancellable_reservation"
        case["regions"][1]["committed_gpus"] = 3
        case["regions"][1]["billing_type"] = "noncancellable_reservation"
        case["allowed_routes"] = [route()]
        result = run_scenario(case)
        self.assertFalse(result["transfers"])
        self.assertEqual(result["net_current_cash_delta_usd"], "0.00")

    def test_negative_net_preserved(self):
        case = scenario()
        case["regions"][1]["committed_gpus"] = 3
        case["regions"][1]["billing_type"] = "noncancellable_reservation"
        case["allowed_routes"] = [route()]
        case["software_usd"] = 20
        result = run_scenario(case)
        self.assertTrue(result["transfers"])
        self.assertLess(float(result["net_current_cash_delta_usd"]), 0)

    def test_every_origin_demand_is_conserved_and_host_capacity_respected(self):
        case = scenario()
        case["regions"][1]["committed_gpus"] = 3
        case["regions"][1]["billing_type"] = "noncancellable_reservation"
        case["allowed_routes"] = [route()]
        hour = run_scenario(case)["hourly"][0]
        for region in ("US", "EU"):
            assigned = sum(a["requests"] for a in hour["candidate_assignments"] if a["origin"] == region)
            self.assertEqual(assigned, hour["origin_requests"][f"{region}/m1"])
            hosted = sum(a["requests"] for a in hour["candidate_assignments"] if a["destination"] == region)
            self.assertLessEqual(hosted, hour["candidate_required_gpus"][f"{region}/m1"] * 48)
            self.assertLessEqual(hour["candidate_required_gpus"][f"{region}/m1"], 4)

    def test_malformed_and_missing_records_fail(self):
        case = scenario()
        case["observations"].pop()
        with self.assertRaisesRegex(ScenarioError, "missing"):
            run_scenario(case)
        case = scenario()
        case["observations"].append(copy.deepcopy(case["observations"][0]))
        with self.assertRaisesRegex(ScenarioError, "duplicate"):
            run_scenario(case)
        case = scenario()
        case["observations"][0]["requests"] = -1
        with self.assertRaisesRegex(ScenarioError, "nonnegative"):
            run_scenario(case)
        case = scenario()
        case["regions"][0]["requests_per_gpu_hour"] = 0
        with self.assertRaisesRegex(ScenarioError, "positive"):
            run_scenario(case)
        case = scenario()
        case["regions"][0]["committed_gpus"] = 2
        with self.assertRaisesRegex(ScenarioError, "billing_type"):
            run_scenario(case)
        case = scenario()
        case["regions"][0]["region"] = ["US"]
        with self.assertRaisesRegex(ScenarioError, "invalid region/model"):
            run_scenario(case)
        case = scenario()
        case["observations"][0]["model_id"] = ["m1"]
        with self.assertRaisesRegex(ScenarioError, "invalid region/model"):
            run_scenario(case)
        case = scenario()
        case["allowed_routes"] = {"origin": "US"}
        with self.assertRaisesRegex(ScenarioError, "expected list"):
            run_scenario(case)
        case = scenario()
        case["observations"][0]["mean_input_tokens"] = -1
        with self.assertRaisesRegex(ScenarioError, "nonnegative"):
            run_scenario(case)
        case = scenario()
        case["observations"][0]["max_ttft_ms"] = 401
        with self.assertRaisesRegex(ScenarioError, "TTFT budget"):
            run_scenario(case)
        case = scenario()
        case["observations"][0]["scenario_id"] = "another"
        with self.assertRaisesRegex(ScenarioError, "scenario_id"):
            run_scenario(case)
        case = scenario()
        case["allowed_routes"] = [route()]
        del case["allowed_routes"][0]["source_ref"]
        with self.assertRaisesRegex(ScenarioError, "source_ref"):
            run_scenario(case)
        case = scenario()
        case["regions"][0]["price_usd_gpu_hour"] = "1e100"
        with self.assertRaisesRegex(ScenarioError, "numeric range"):
            run_scenario(case)
        case = scenario()
        case["observations"][0]["requests"] = 1_000_000_001
        with self.assertRaisesRegex(ScenarioError, "at most"):
            run_scenario(case)
        case = scenario()
        case["regions"][0]["source_ref"] = "x" * 1025
        with self.assertRaisesRegex(ScenarioError, "source_ref"):
            run_scenario(case)
        for control in (chr(127), chr(0x202e)):
            case = scenario()
            case["regions"][0]["source_ref"] = "source" + control
            with self.assertRaisesRegex(ScenarioError, "printable"):
                run_scenario(case)
            case = scenario()
            case["regions"][0]["region"] = "US" + control
            with self.assertRaisesRegex(ScenarioError, "invalid region/model"):
                run_scenario(case)

    def test_infeasible_capacity_never_returns_savings(self):
        case = scenario()
        case["regions"][0]["capacity_gpus"] = 2
        with self.assertRaisesRegex(ScenarioError, "INFEASIBLE"):
            run_scenario(case)

    def test_csv_input_and_report_export(self):
        case = scenario()
        source = StringIO(newline="")
        writer = csv.DictWriter(source, fieldnames=CSV_OBSERVATION_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(case["observations"])
        parsed = parse_observations_csv(source.getvalue())
        case["observations"] = parsed
        report = run_scenario(case)
        report["exported_utc"] = "2026-10-26T00:00:00Z"
        exported = list(csv.DictReader(StringIO(render_report_csv(report))))
        costs = {row["metric"]: row["value"] for row in exported if row["record_type"] == "cost"}
        self.assertEqual(costs["baseline_compute_usd"], "11.97")
        self.assertEqual(costs["net_current_cash_delta_usd"], "0.00")
        self.assertTrue(all(row["exported_utc"] == "2026-10-26T00:00:00Z" for row in exported))
        self.assertEqual(sum(int(row["requests"]) for row in exported if row["record_type"] == "assignment"), 100)
        self.assertTrue(any(row["record_type"] == "provenance" and row["value"] == "synthetic:fixture" for row in exported))
        self.assertEqual(report["input_provenance"]["observations"][0]["rows"], 2)
        self.assertTrue(any("TTFT" in warning for warning in report["limitations"]))
        with self.assertRaisesRegex(ScenarioError, "header"):
            parse_observations_csv("requests,origin_region\n1,US\n")
        with self.assertRaisesRegex(ScenarioError, "wrong column count"):
            parse_observations_csv(source.getvalue() + "bad,row\n")

    def test_csv_formula_text_is_escaped(self):
        case = scenario()
        case["regions"][0]["region"] = "=SUM(1,1)"
        case["observations"][0]["origin_region"] = "=SUM(1,1)"
        report = run_scenario(case)
        exported = list(csv.DictReader(StringIO(render_report_csv(report))))
        assignments = [row for row in exported if row["record_type"] == "assignment"]
        self.assertTrue(any(row["origin"].startswith("'=") for row in assignments))

    def test_three_region_thirty_day_replay(self):
        case = scenario(hours=720, region_count=3)
        self.assertEqual(len(case["observations"]), 2160)
        first = run_scenario(case)
        second = run_scenario(case)
        self.assertEqual(first, second)
        self.assertEqual(first["hours"], 720)
        self.assertEqual(len(first["hourly"]), 720)

    def test_decimal_context_is_local_and_extreme_zero_is_normalized(self):
        original_precision = getcontext().prec
        case = scenario()
        case["regions"][0]["price_usd_gpu_hour"] = "0e999999"
        self.assertEqual(run_scenario(case)["baseline_compute_usd"], "0.00")
        self.assertEqual(getcontext().prec, original_precision)

    def test_seeded_financial_and_capacity_invariants(self):
        rng = random.Random(24004)
        names = ("US", "EU", "ASIA")
        for _ in range(50):
            case = scenario(region_count=3)
            for region, observation in zip(case["regions"], case["observations"]):
                region["price_usd_gpu_hour"] = str(rng.randrange(1, 600) / 100)
                region["committed_gpus"] = rng.randrange(4)
                region["billing_type"] = "noncancellable_reservation" if region["committed_gpus"] else "on_demand"
                observation["requests"] = rng.randrange(145)
            case["allowed_routes"] = []
            for origin in names:
                for destination in names:
                    if origin == destination or not rng.randrange(2):
                        continue
                    edge = route()
                    edge["origin"], edge["destination"] = origin, destination
                    edge["estimated_p95_ms"] = rng.randrange(100, 501)
                    edge["egress_usd_gb"] = str(rng.randrange(0, 200) / 100)
                    case["allowed_routes"].append(edge)
            result = run_scenario(case)
            hour = result["hourly"][0]
            for region in names:
                origin_total = sum(row["requests"] for row in hour["candidate_assignments"] if row["origin"] == region)
                hosted_total = sum(row["requests"] for row in hour["candidate_assignments"] if row["destination"] == region)
                self.assertEqual(origin_total, hour["origin_requests"][f"{region}/m1"])
                self.assertLessEqual(hosted_total, hour["candidate_required_gpus"][f"{region}/m1"] * 48)
                self.assertLessEqual(hour["candidate_required_gpus"][f"{region}/m1"], 4)
            allowed = {(row["origin"], row["destination"]) for row in case["allowed_routes"] if row["estimated_p95_ms"] <= 400}
            self.assertTrue(all((row["origin"], row["destination"]) in allowed for row in result["transfers"]))
            prices = {row["region"]: Decimal(row["price_usd_gpu_hour"]) for row in case["regions"]}
            commitments = {row["region"]: row["committed_gpus"] for row in case["regions"]}
            for prefix in ("baseline", "candidate"):
                expected = sum(Decimal(max(hour[f"{prefix}_required_gpus"][f"{region}/m1"], commitments[region])) * prices[region] for region in names)
                self.assertEqual(Decimal(result[f"{prefix}_compute_usd"]), expected.quantize(Decimal("0.01")))
            self.assertLessEqual(Decimal(result["perfect_pooling_compute_lower_bound_usd"]), Decimal(result["candidate_compute_usd"]))
            self.assertEqual(result["theoretical_gpu_hours_reduction"], result["baseline_required_gpu_hours"] - result["candidate_required_gpu_hours"])
            expected_network = sum((Decimal(row["network_usd_exact"]) for row in result["transfers"]), Decimal(0))
            self.assertEqual(Decimal(result["network_usd"]), expected_network.quantize(Decimal("0.01")))
            expected_net = Decimal(result["baseline_compute_usd"]) - Decimal(result["candidate_compute_usd"]) - expected_network
            self.assertEqual(Decimal(result["net_current_cash_delta_usd"]), expected_net.quantize(Decimal("0.01")))


if __name__ == "__main__":
    unittest.main()
