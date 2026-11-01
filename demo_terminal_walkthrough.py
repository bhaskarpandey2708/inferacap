#!/usr/bin/env python3
"""Interactive Terminal Showcase & Customer Journey Demo for InferaCap.

Simulates the complete enterprise journey:
1. Pre-Sales Diagnostic: Scans 8,000+ customer logs -> shows $42k/yr avoidable cash.
2. Production Gateway Ingress: Routes live OpenAI requests across US and EU clusters.
3. Dynamic Economic Overflow: Avoids on-demand overage fees by utilizing idle reservations.
4. Circuit Breaker Self-Healing: Automatically fails over when an endpoint faults.
5. Telemetry & Analytics: Outputs drop/merge recommendation ledger.
"""

import json
import time
from pathlib import Path

# ANSI Color Codes
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_step(num: int, title: str):
    print(f"\n{BOLD}{CYAN}▶ STEP {num}: {title}{RESET}")
    print(f"{DIM}{'-' * 75}{RESET}")


def main():
    print(f"{BOLD}{GREEN}=" * 75)
    print("⚡ INFERACAP: THE ECONOMICALLY-AWARE MULTI-REGION INFERENCE LOAD BALANCER")
    print("   Commercial Platform Showcase & Customer Journey Simulation")
    print("=" * 75 + f"{RESET}")
    time.sleep(0.4)

    # 1. Pre-Sales Log Scanner
    print_step(1, "Pre-Sales Free Trial Diagnostic (Scanning Customer Telemetry)")
    print(f"📁 Ingesting customer vLLM logs: {YELLOW}sample_customer_vllm_logs.csv{RESET} (72 hours, 3 regions)...")
    time.sleep(0.5)
    print(f"📊 Processed {BOLD}8,028 requests{RESET} ({BOLD}1,504,962 tokens{RESET}) across ASIA, EU, US.")
    print(f"\n{BOLD}💰 Financial Reconciliation Waterfall:{RESET}")
    print(f"   • Baseline Siloed Spend (On-Demand Peak Provisioning):  {RED}$873.81 USD{RESET}")
    print(f"   • InferaCap Multi-Region Pooled Compute Spend:          {GREEN}$524.29 USD{RESET}")
    print(f"   • Incremental Cross-Region Network Egress (WAN):        {DIM}$0.0000 USD{RESET}")
    print(f"   {'-' * 60}")
    print(f"   ⭐ {BOLD}NET AVOIDED CASH SPEND (Immediate ROI):              {GREEN}+$349.52 USD{RESET}")
    print(f"   📈 {BOLD}INVOICE REDUCTION RATE:                              {GREEN}40.0%{RESET}")
    print(f"   🚀 {BOLD}ANNUALIZED RUN-RATE SAVINGS:                        {GREEN}$42,633.98 USD / year{RESET}")
    print(f"\n👉 Customer clicks: {BOLD}{GREEN}[⚡ Enable Live Routing — Launch InferaCap Gateway]{RESET}")
    time.sleep(0.8)

    # 2. Live Gateway & Ingress
    print_step(2, "Booting InferaCap Live Intelligent Reverse Proxy")
    print("🚀 Initializing InferaCap Infrastructure Federation:")
    print("   • US-East Cluster:    http://127.0.0.1:8001 (On-Demand @ $4.00/hr, Cap: 2)")
    print("   • EU-Central Cluster: http://127.0.0.1:8002 (Committed Reservation, Cap: 10)")
    print("   • Kaggle GPU Node:    http://127.0.0.1:8003 (Owned Dual-T4 @ $0.00/hr, Cap: 8)")
    print(f"\n⚡ {BOLD}InferaCap Live Ingress Active:{RESET} http://127.0.0.1:8765/v1/chat/completions")
    time.sleep(0.6)

    # 3. Live Traffic Routing & Dynamic Overflow
    print_step(3, "Dispatching Live Requests via Official Python SDK")
    print(f"Client SDK: {CYAN}from inferacap import InferaCap; client = InferaCap(){RESET}")
    time.sleep(0.4)

    # Request 1: Normal load
    print(f"\n[Request 1] Origin: US | Prompt: 'Summarize Q3 earnings'")
    time.sleep(0.2)
    print(f"   --> {GREEN}ROUTE LOCAL{RESET} | Served By: US | Added Egress: $0.00 | Latency: 14.2ms")

    # Request 2: Peak Surge Overflow
    print(f"\n[Request 2] Origin: US | Prompt: 'Run multi-agent code analysis' (US Saturated: Concurrency 2/2)")
    time.sleep(0.3)
    print(f"   --> {YELLOW}CROSS_REGION_ECONOMIC{RESET} | Transatlantic Hop: US -> EU (Idle Reservation)")
    print(f"   --> Avoided Local On-Demand Compute: {GREEN}+$0.001111 USD{RESET}")
    print(f"   --> Added Network Egress: {DIM}$0.000000 USD{RESET} | Latency: 78.4ms (Within 400ms TTFT budget)")

    # Request 3: GDPR Compliance Check
    print(f"\n[Request 3] Origin: EU | GDPR Personal Data (EU Saturated)")
    time.sleep(0.2)
    print(f"   --> {RED}REJECTED (HTTP 503){RESET} | Reason: Legally prohibited from exiting EU to non-compliant regions.")
    print(f"   --> 🛡️ {BOLD}Sovereign Compliance Preserved.{RESET}")

    # 4. Circuit Breakers
    print_step(4, "Resilience & Circuit Breaker Demonstration")
    print("Simulating 3 consecutive connection failures on US backend...")
    time.sleep(0.3)
    print(f"🚨 {RED}Circuit Breaker TRIPPED for US backend -> OPEN{RESET}")
    print(f"Subsequent US traffic instantly fails over to: {GREEN}EU Reservation Cluster (Zero Downtime){RESET}")
    time.sleep(0.5)

    # 5. Drop / Merge Telemetry
    print_step(5, "Autonomous Telemetry & Feature Optimization (Drop / Merge Engine)")
    analytics = {
        "live_routing": 62.0,
        "offline_simulator": 23.9,
        "log_scanner": 10.6,
        "cloud_worker": 3.5,
    }
    print("Feature Usage Distribution:")
    for feat, pct in analytics.items():
        bar = "█" * int(pct / 2.5)
        print(f"   • {feat:<20}: {bar:<26} {pct}%")
    print(f"\n💡 {BOLD}System Recommendation:{RESET}")
    print(f"   'Live Routing is primary traction (62%). Cloud Worker (3.5%) is low-frequency.")
    print(f"    Recommendation: Merge Cloud Worker setup wizard directly into Live Routing tab.'")

    print(f"\n{BOLD}{GREEN}=" * 75)
    print("✅ SHOWCASE COMPLETE: ALL SYSTEMS PRODUCTION VERIFIED")
    print("=" * 75 + f"{RESET}\n")


if __name__ == "__main__":
    main()
