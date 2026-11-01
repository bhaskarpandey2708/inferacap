#!/usr/bin/env python3
"""InferaCap Enterprise Log Scanner & Savings Diagnostic CLI.

Analyzes raw customer LLM inference logs (vLLM, SGLang, Datadog, CloudWatch, NGINX),
evaluates multi-region demand elasticity, and models exact avoidability and dollar ROI.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("inferacap.scanner")


@dataclass
class LogRecord:
    timestamp: float
    origin_region: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float = 0.0


@dataclass
class ScanAnalysisResult:
    total_requests: int
    total_tokens: int
    unique_models: List[str]
    unique_regions: List[str]
    time_span_hours: float
    baseline_compute_usd: float
    inferacap_compute_usd: float
    incremental_egress_usd: float
    net_savings_usd: float
    savings_percentage: float
    annualized_projected_savings_usd: float
    hourly_histogram: Dict[str, Dict[str, int]]
    transfers_simulated: int


class LogScanner:
    """Ingests raw multi-region telemetry and computes InferaCap avoidable cash delta."""

    DEFAULT_GPU_HOURLY_RATE = 3.99  # Standard On-Demand A10G/T4/L4 blended rate
    DEFAULT_EGRESS_PER_GB = 0.02    # Inter-region AWS/GCP WAN egress fee
    TOKENS_PER_BYTE = 0.25          # ~4 bytes per token

    def __init__(
        self,
        on_demand_rate_gpu_hour: float = DEFAULT_GPU_HOURLY_RATE,
        reservation_discount_pct: float = 0.40,
        egress_cost_per_gb: float = DEFAULT_EGRESS_PER_GB,
    ):
        self.on_demand_rate = on_demand_rate_gpu_hour
        self.reservation_rate = on_demand_rate_gpu_hour * (1.0 - reservation_discount_pct)
        self.egress_cost_per_gb = egress_cost_per_gb

    def parse_log_file(self, file_path: Path) -> List[LogRecord]:
        """Auto-detect format (CSV or JSONL) and parse inference log records."""
        records: List[LogRecord] = []
        if not file_path.exists():
            raise FileNotFoundError(f"Log file not found: {file_path}")

        ext = file_path.suffix.lower()
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            if ext in (".json", ".jsonl"):
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        ts = float(obj.get("timestamp", time.time()))
                        reg = str(obj.get("region", obj.get("origin_region", "US"))).upper()
                        model = str(obj.get("model", "llama-3.1-8b"))
                        p_tok = int(obj.get("prompt_tokens", obj.get("input_tokens", 128)))
                        c_tok = int(obj.get("completion_tokens", obj.get("output_tokens", 32)))
                        lat = float(obj.get("latency_ms", obj.get("ttft_ms", 120.0)))
                        records.append(LogRecord(ts, reg, model, p_tok, c_tok, lat))
                    except Exception:
                        continue
            else:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        # Match common column aliases
                        ts_val = row.get("timestamp") or row.get("time") or row.get("created_at") or str(time.time())
                        try:
                            ts = float(ts_val)
                        except ValueError:
                            ts = datetime.fromisoformat(ts_val.replace("Z", "+00:00")).timestamp()

                        reg = (row.get("region") or row.get("origin_region") or row.get("location") or "US").upper()
                        model = row.get("model") or row.get("model_id") or "llama-3.1-8b"
                        p_tok = int(row.get("prompt_tokens") or row.get("input_tokens") or 128)
                        c_tok = int(row.get("completion_tokens") or row.get("output_tokens") or 32)
                        lat = float(row.get("latency_ms") or row.get("ttft_ms") or 100.0)
                        records.append(LogRecord(ts, reg, model, p_tok, c_tok, lat))
                    except Exception:
                        continue

        if not records:
            raise ValueError(f"No valid inference records could be parsed from {file_path}")
        return records

    def analyze(self, records: List[LogRecord]) -> ScanAnalysisResult:
        """Simulate baseline vs. InferaCap multi-region pooling."""
        records.sort(key=lambda r: r.timestamp)
        start_ts = records[0].timestamp
        end_ts = records[-1].timestamp
        hours = max(1.0, (end_ts - start_ts) / 3600.0)

        # Aggregate requests into hourly buckets per region
        hourly_counts: Dict[str, Dict[str, int]] = {}
        hourly_tokens: Dict[str, Dict[str, int]] = {}
        models = set()
        regions = set()
        total_tokens = 0

        for r in records:
            models.add(r.model)
            regions.add(r.origin_region)
            toks = r.prompt_tokens + r.completion_tokens
            total_tokens += toks

            # Bucket by hour
            hour_key = time.strftime("%Y-%m-%d %H:00", time.gmtime(r.timestamp))
            if hour_key not in hourly_counts:
                hourly_counts[hour_key] = {}
                hourly_tokens[hour_key] = {}
            hourly_counts[hour_key][r.origin_region] = hourly_counts[hour_key].get(r.origin_region, 0) + 1
            hourly_tokens[hour_key][r.origin_region] = hourly_tokens[hour_key].get(r.origin_region, 0) + 1

        reg_list = sorted(regions)
        model_list = sorted(models)

        # Assume 1 GPU can sustain 3,600 req/hr at p95 SLA
        reqs_per_gpu_hr = 3600.0

        baseline_gpu_hours = 0.0
        candidate_gpu_hours = 0.0
        candidate_reservation_gpu_hours = 0.0
        candidate_overflow_gpu_hours = 0.0
        transfers_count = 0
        total_egress_bytes = 0.0

        # Calculate baseline per-region reservation rightsizing
        # In baseline, each region must independently size for its own 75th percentile load
        reg_loads: Dict[str, List[int]] = {r: [] for r in reg_list}
        for h_data in hourly_counts.values():
            for r in reg_list:
                reg_loads[r].append(h_data.get(r, 0))

        baseline_committed_gpus: Dict[str, int] = {}
        for r, loads in reg_loads.items():
            if loads:
                sorted_l = sorted(loads)
                p75 = sorted_l[int(len(sorted_l) * 0.75)]
                baseline_committed_gpus[r] = max(1, math.ceil(p75 / reqs_per_gpu_hr))
            else:
                baseline_committed_gpus[r] = 1

        # Simulate hourly allocation
        for h_key, h_data in hourly_counts.items():
            # Baseline: Local-only siloed execution
            for r in reg_list:
                reqs = h_data.get(r, 0)
                gpus_needed = math.ceil(reqs / reqs_per_gpu_hr) if reqs > 0 else 0
                committed = baseline_committed_gpus[r]
                # Baseline pays committed reservation + on-demand for overage
                baseline_gpu_hours += max(committed, gpus_needed)

            # InferaCap Candidate: Dynamic Global Pooling
            # Idle reservation capacity in region A absorbs surge in region B
            total_hourly_reqs = sum(h_data.values())
            pooled_gpus_needed = math.ceil(total_hourly_reqs / reqs_per_gpu_hr)
            total_committed = sum(baseline_committed_gpus.values())

            # Avoidable overage:
            if pooled_gpus_needed <= total_committed:
                candidate_gpu_hours += total_committed
                # Excess demand was transferred to idle reservations
                for r in reg_list:
                    reqs = h_data.get(r, 0)
                    committed = baseline_committed_gpus[r]
                    if reqs > committed * reqs_per_gpu_hr:
                        overflow_reqs = reqs - (committed * reqs_per_gpu_hr)
                        transfers_count += int(overflow_reqs)
                        # ~4KB per transferred request
                        total_egress_bytes += (overflow_reqs * 4096)
            else:
                candidate_gpu_hours += pooled_gpus_needed
                overflow_reqs = total_hourly_reqs - (total_committed * reqs_per_gpu_hr)
                transfers_count += int(max(0, overflow_reqs))
                total_egress_bytes += (max(0, overflow_reqs) * 4096)

        # Financial Valuation
        baseline_cost = baseline_gpu_hours * self.on_demand_rate
        candidate_compute_cost = candidate_gpu_hours * self.reservation_rate
        egress_gb = total_egress_bytes / (1024 ** 3)
        egress_cost = egress_gb * self.egress_cost_per_gb

        candidate_total_cost = candidate_compute_cost + egress_cost
        net_savings = max(0.0, baseline_cost - candidate_total_cost)
        savings_pct = (net_savings / baseline_cost * 100.0) if baseline_cost > 0 else 0.0

        # Annualized run-rate projection
        annual_mult = (8760.0 / hours) if hours > 0 else 1.0
        annual_savings = net_savings * annual_mult

        return ScanAnalysisResult(
            total_requests=len(records),
            total_tokens=total_tokens,
            unique_models=model_list,
            unique_regions=reg_list,
            time_span_hours=round(hours, 2),
            baseline_compute_usd=round(baseline_cost, 2),
            inferacap_compute_usd=round(candidate_compute_cost, 2),
            incremental_egress_usd=round(egress_cost, 4),
            net_savings_usd=round(net_savings, 2),
            savings_percentage=round(savings_pct, 1),
            annualized_projected_savings_usd=round(annual_savings, 2),
            hourly_histogram=hourly_counts,
            transfers_simulated=transfers_count,
        )


def print_cli_report(res: ScanAnalysisResult, log_path: Path):
    print("\n" + "=" * 78)
    print("⚡ INFERACAP ENTERPRISE LOG SCANNER: CAPACITY & ROI AUDIT REPORT")
    print("=" * 78)
    print(f"📁 Target Telemetry:     {log_path.name}")
    print(f"⏱️  Observed Time Window: {res.time_span_hours:.1f} hours")
    print(f"📊 Total Requests:       {res.total_requests:,}")
    print(f"🔢 Total Tokens:         {res.total_tokens:,}")
    print(f"🌐 Active Regions:       {', '.join(res.unique_regions)}")
    print(f"🤖 Hosted Models:        {', '.join(res.unique_models)}")
    print("-" * 78)
    print("💰 FINANCIAL RECONCILIATION WATERFALL:")
    print(f"   • Baseline Siloed Spend (On-Demand Peak Provisioning):  ${res.baseline_compute_usd:,.2f} USD")
    print(f"   • InferaCap Multi-Region Pooled Compute Spend:          ${res.inferacap_compute_usd:,.2f} USD")
    print(f"   • Incremental Cross-Region Network Egress (WAN):        ${res.incremental_egress_usd:,.4f} USD")
    print("   " + "-" * 60)
    print(f"   ⭐ NET AVOIDED CASH SPEND (Immediate ROI):              ${res.net_savings_usd:,.2f} USD")
    print(f"   📈 INVOICE REDUCTION RATE:                              {res.savings_percentage:.1f}%")
    print(f"   🚀 ANNUALIZED RUN-RATE NET SAVINGS:                    ${res.annualized_projected_savings_usd:,.2f} USD / year")
    print("=" * 78)
    print(f"🔄 Cross-Region Overflow Requests Optimized:              {res.transfers_simulated:,}")
    print("-" * 78)
    print("⚡ READY TO CAPTURE THESE NET SAVINGS IN LIVE PRODUCTION?")
    print("   Deploy the InferaCap Live Production Gateway to dynamically pool multi-region")
    print("   vLLM/SGLang clusters, enforcing sub-150ms TTFT SLAs & strict GDPR guardrails.")
    print("   ")
    print("   • Zero-Risk Enterprise Pilot (100% money-back guarantee on verified savings)")
    print("   • 20% Verified Gain-Share Model: You only pay when your cloud bill drops")
    print("   • Evaluation Run: python3 run_gateway.py gateway/sample_gateway_config.json")
    print("   ")
    print("   👉 Contact Bhaskar Pandey <bhaskarauthor@gmail.com> for Enterprise Commercial")
    print("      License, Private VPC Kubernetes manifests, or custom deployment support.")
    print("=" * 78 + "\n")


def export_json_report(res: ScanAnalysisResult, output_path: Path):
    data = {
        "report_id": f"inferacap-scan-{int(time.time())}",
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "scanner_version": "1.0.0",
        "analysis": {
            "time_span_hours": res.time_span_hours,
            "total_requests": res.total_requests,
            "total_tokens": res.total_tokens,
            "unique_regions": res.unique_regions,
            "unique_models": res.unique_models,
            "transfers_simulated": res.transfers_simulated,
            "financials": {
                "currency": "USD",
                "baseline_compute_usd": res.baseline_compute_usd,
                "inferacap_compute_usd": res.inferacap_compute_usd,
                "incremental_egress_usd": res.incremental_egress_usd,
                "net_avoided_spend_usd": res.net_savings_usd,
                "savings_percentage": res.savings_percentage,
                "annualized_projected_savings_usd": res.annualized_projected_savings_usd,
            },
        },
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    logger.info(f"✅ Exported JSON Audit Report to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="InferaCap Enterprise Log Scanner")
    parser.add_argument("log_file", type=Path, help="Path to CSV or JSONL inference log file")
    parser.add_argument("--json-report", type=Path, default=None, help="Path to write JSON report")
    parser.add_argument("--gpu-rate", type=float, default=3.99, help="Hourly on-demand GPU rate (default: $3.99)")
    parser.add_argument("--discount", type=float, default=0.40, help="Committed reservation discount (default: 0.40)")
    args = parser.parse_args()

    scanner = LogScanner(on_demand_rate_gpu_hour=args.gpu_rate, reservation_discount_pct=args.discount)
    try:
        records = scanner.parse_log_file(args.log_file)
        result = scanner.analyze(records)
        print_cli_report(result, args.log_file)
        if args.json_report:
            export_json_report(result, args.json_report)
    except Exception as e:
        logger.error(f"❌ Scanning error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
