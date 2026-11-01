#!/usr/bin/env python3
"""InferaCap Cinematic Terminal Video & Interactive Walkthrough.

Runs a timed, colorized, explanatory live demonstration of the complete
InferaCap value proposition, pre-sales log scanner, and live multi-region routing.
"""

from __future__ import annotations

import os
import sys
import time

# ANSI Terminal Formatting
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
PURPLE = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def typewrite(text: str, delay: float = 0.015):
    """Simulate realistic typing cadence."""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write("\n")
    sys.stdout.flush()


def spinner(duration: float = 1.0, msg: str = "Processing"):
    """Display an inline rotating spinner."""
    chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    start = time.time()
    idx = 0
    while time.time() - start < duration:
        sys.stdout.write(f"\r{CYAN}{chars[idx % len(chars)]}{RESET} {msg}...")
        sys.stdout.flush()
        time.sleep(0.08)
        idx += 1
    sys.stdout.write(f"\r✔ {msg} [DONE]\n")
    sys.stdout.flush()


def banner():
    print(f"\n{BOLD}{GREEN}=" * 78)
    print("⚡ INFERACAP: THE ECONOMICALLY-AWARE MULTI-REGION INFERENCE LOAD BALANCER")
    print("   Live Terminal Demonstration & Product Walkthrough (Path 3 Architecture)")
    print("=" * 78 + f"{RESET}\n")


def chapter(num: int, title: str):
    print(f"\n{BOLD}{PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    print(f"{BOLD}{CYAN}▶ CHAPTER {num}: {title.upper()}{RESET}")
    print(f"{BOLD}{PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}\n")
    time.sleep(0.4)


def main():
    banner()
    time.sleep(0.6)

    # CHAPTER 1: The Problem
    chapter(1, "The Diurnal Utilization Dilemma in Multi-Region AI")
    print("Large language model traffic follows human sunlight curves:")
    print(f" • At {BOLD}2:00 PM in New York{RESET}, North American vLLM clusters hit 100% capacity.")
    print(f"   Teams burst onto expensive {RED}on-demand GPU instances ($4.00+/hr){RESET} to maintain latency.")
    print(f" • At that exact moment ({BOLD}8:00 PM in Frankfurt{RESET}), European GPU reservations sit {YELLOW}75%+ idle{RESET}.")
    print(f" • Existing proxies (LiteLLM, Cloudflare, Envoy) are {RED}contract-blind{RESET}: they route by raw ping.")
    time.sleep(1.2)

    # CHAPTER 2: The Free Audit Diagnostic
    chapter(2, "Running the Free Open-Source Log Scanner (Path 3 Magnet)")
    sys.stdout.write(f"{DIM}$ {RESET}")
    typewrite(f"{CYAN}inferacap-scan {YELLOW}sample_customer_vllm_logs.csv{RESET} --discount 0.40")
    spinner(1.2, "Ingesting 8,028 inference access logs")
    print(f" • Observed Time Window: {BOLD}71.8 hours{RESET} across US, EU, and ASIA")
    print(f" • Models Evaluated:     {BOLD}llama-3.1-8b, qwen2.5-coder{RESET}")
    print(f" • Total Tokens Parsed:  {BOLD}1,504,962 tokens{RESET}")
    time.sleep(0.8)

    # CHAPTER 3: The Financial Waterfall
    chapter(3, "The Undeniable Financial Reconciliation Waterfall")
    print("=" * 78)
    print(f"💰 {BOLD}FINANCIAL RECONCILIATION WATERFALL:{RESET}")
    print(f"   • Baseline Siloed Spend (On-Demand Peak Provisioning):  {RED}$873.81 USD{RESET}")
    print(f"   • InferaCap Multi-Region Pooled Compute Spend:          {GREEN}$524.29 USD{RESET}")
    print(f"   • Incremental Cross-Region Network Egress (WAN):        {DIM}$0.0000 USD{RESET}")
    print("   " + "-" * 60)
    print(f"   ⭐ {BOLD}NET AVOIDED CASH SPEND (Immediate ROI):              {GREEN}+$349.52 USD{RESET}")
    print(f"   📈 {BOLD}INVOICE REDUCTION RATE:                              {GREEN}40.0%{RESET}")
    print(f"   🚀 {BOLD}ANNUALIZED RUN-RATE NET SAVINGS:                    {GREEN}$42,633.98 USD / year{RESET}")
    print("=" * 78)
    print(f"\n{BOLD}{YELLOW}💡 The Head of Infrastructure shows this exact audit to the CFO.{RESET}")
    print("   The business case is undeniable: 40% reduction with zero code changes.")
    time.sleep(1.2)

    # CHAPTER 4: Booting the Live Gateway
    chapter(4, "Booting the InferaCap Commercial Production Gateway")
    sys.stdout.write(f"{DIM}$ {RESET}")
    typewrite(f"{CYAN}inferacap-gateway {YELLOW}gateway/sample_gateway_config.json{RESET} --port 8765")
    spinner(0.8, "Binding OpenAI-compatible reverse proxy on :8765")
    print(f"⚡ {GREEN}{BOLD}InferaCap Live Intelligent Gateway Active:{RESET} http://127.0.0.1:8765/v1")
    print("   • US-East Cluster:    http://127.0.0.1:8001 (On-Demand @ $4.00/hr, Max Concurrency: 2)")
    print("   • EU-Central Cluster: http://127.0.0.1:8002 (Committed Annual Reservation, Max: 10)")
    print("   • Kaggle GPU Node:    http://127.0.0.1:8003 (Owned Dual-T4 @ $0.00/hr, Max: 8)")
    time.sleep(1.0)

    # CHAPTER 5: Live Routing & Tail-Latency Budgeting
    chapter(5, "Live Request Dispatch & Tail-Latency SLA Invariants")
    print(f"{CYAN}from inferacap import InferaCap; client = InferaCap(){RESET}\n")

    print(f"[Request #101] Prompt: 'Summarize quarterly financials' | Origin: US")
    time.sleep(0.3)
    print(f"  ✔ {GREEN}ROUTE LOCAL{RESET} --> Served by US | TTFT: {BOLD}14.2ms{RESET} | Egress: $0.00")
    time.sleep(0.5)

    print(f"\n[Request #102] Prompt: 'Analyze distributed logs' | Origin: US (US Saturated: 2/2 in-flight)")
    print("  • Contract Avoidability Engine evaluates transatlantic hop (US -> EU).")
    print("  • SLA Invariant: Measured RTT is 75ms (Client TTFT Budget is 300ms).")
    time.sleep(0.4)
    print(f"  ✔ {YELLOW}CROSS_REGION_ECONOMIC{RESET} --> Routed: US -> EU (Idle Sunk Reservation)")
    print(f"  ✔ {GREEN}Avoided On-Demand Cost: +$0.001111 USD{RESET} | TTFT: {BOLD}78.4ms{RESET} (Under budget)")
    time.sleep(0.8)

    # CHAPTER 6: Sovereign GDPR Guardrails
    chapter(6, "Directional GDPR Article 44 Sovereignty Enforcement")
    print(f"[Request #103] Prompt: 'Analyze European medical records' | Origin: EU (EU Peak Load)")
    print("  • Policy Gate: Directional rule EU -> US has residency_permission=False.")
    time.sleep(0.4)
    print(f"  🛡️  {YELLOW}{BOLD}GDPR GUARDRAIL ACTIVATED:{RESET} Remote transfer to US silicon rejected.")
    print(f"  ✔ Overflowed locally to compliant Kaggle Cloud Dual-T4 cluster ($0.00/hr).")
    print(f"  ✔ European customer data never leaves sovereign soil. 100% compliant.")
    time.sleep(0.8)

    # CHAPTER 7: Circuit Breakers & Self-Healing
    chapter(7, "Circuit Breakers & Autonomous Endpoint Self-Healing")
    print(f"🚨 {RED}SIMULATING SUDDEN OUTAGE IN US-EAST CLUSTER:{RESET}")
    print("  • Attempting connection to http://127.0.0.1:8001 -> Connection Refused")
    time.sleep(0.3)
    print("  • Consecutive failure count: 3 / 3")
    print(f"  ⚡ {RED}{BOLD}CIRCUIT BREAKER TRIPPED --> STATE: OPEN{RESET} (Evicted from active pool)")
    time.sleep(0.3)
    print(f"  ✔ {GREEN}INSTANT AUTO-FAILOVER:{RESET} Shifted in-flight stream to EU in 1.1ms.")
    print("  ✔ Zero dropped tokens; zero client 500 errors.")
    print(f"  ✔ Active health probes recover endpoint 10s later --> {GREEN}STATE: CLOSED{RESET}")
    time.sleep(1.0)

    # CHAPTER 8: Commercial Model & Close
    chapter(8, "Commercial Model: Risk-Free 20% Gain-Share")
    print("=" * 78)
    print("🏁 INFERACAP COMMERCIAL ARCHITECTURE (Path 3):")
    print("   1. Open-Source Diagnostic Magnet (Apache 2.0):")
    print("      • Scan your logs for free in 30 seconds: inferacap-scan logs.csv")
    print("      • Zero security friction; builds CFO-ready business case.")
    print("   ")
    print("   2. Commercial Production Gateway (Commercial License):")
    print("      • Deploy InferaCap Gateway in front of your vLLM clusters.")
    print("      • 20% Verified Gain-Share Model: You only pay when your cloud bill drops.")
    print("      • Or Team Pro subscription at $499/month.")
    print("   ")
    print(f"👉 Contact {BOLD}Bhaskar Pandey{RESET} <bhaskarauthor@gmail.com> for Enterprise Pilot Access.")
    print("=" * 78)
    print(f"\n{BOLD}{CYAN}🎥 For interactive video playback, open:{RESET} demo_terminal_video.html")
    print(f"{BOLD}{GREEN}🌐 For the live web dashboard, open:{RESET}       http://127.0.0.1:8764/\n")


if __name__ == "__main__":
    main()
