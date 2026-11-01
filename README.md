# ⚡ InferaCap: The Economically-Aware Multi-Region Inference Load Balancer

[![License](https://img.shields.io/badge/License-Apache_2.0_|_Commercial-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9_|_3.10_|_3.11_|_3.12-brightgreen.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/Tests-64_Passing-emerald.svg)](tests/)
[![Architecture](https://img.shields.io/badge/Architecture-Clean--Room_Independent-blueviolet.svg)](#architecture)
[![Overhead](https://img.shields.io/badge/Proxy_Overhead-%3C1.8ms-orange.svg)](#performance)

**Stop paying 3x on-demand GPU surcharges when your European reservations are sitting 80% idle overnight.**  
InferaCap is a lightweight, drop-in OpenAI-compatible reverse proxy that pools your multi-region vLLM, SGLang, and Ollama clusters. It dynamically routes live inference requests to idle pre-paid capacity across time zones while strictly enforcing tail-latency budgets (TTFT SLAs) and sovereign GDPR data residency laws.

---

```
   ┌────────────────────────────────────────────────────────────────────────┐
   │                       CLIENT INFERENCE TRAFFIC                         │
   │           (OpenAI SDK, LiteLLM, Open WebUI, Cursor, Agents)            │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       │ POST /v1/chat/completions (SSE)
                                       ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │                 ⚡ INFERACAP REVERSE PROXY & FINOPS ROUTER                   │
  │                                                                              │
  │   1. Contract Waterfall:    Owned ($0) > Committed RIs > On-Demand ($$$)     │
  │   2. Latency SLA Invariant: Checked against client X-TTFT-Budget-MS          │
  │   3. Sovereign Guardrail:   Directional GDPR allowlists (EU data stays in EU)│
  │   4. Resilience:            Active Circuit Breakers & Auto-Failover (<2ms)   │
  └───────┬────────────────────────────┬────────────────────────────┬────────────┘
          │ (0 WAN egress)             │ (Transatlantic Hop)        │ (Encrypted Tunnel)
          ▼                            ▼                            ▼
   [ US-East Cluster ]          [ EU-Central Cluster ]       [ Kaggle Cloud Dual-T4 ]
   • vLLM / A10G Pool           • SGLang / H100 RIs          • Free Cloud Quota
   • On-Demand: $4.00/hr        • Amortized: $0.00 marginal  • $0.00/hr Owned Silicon
```

---

## 🚀 Quickstart: Free 30-Second Log Audit (Path 3 Magnet)

Before touching live traffic, run our open-source diagnostic CLI on your historical logs to uncover your exact avoidable GPU spend:

```bash
# Install via pip
pip install inferacap

# Scan your historical vLLM or CloudWatch logs
inferacap-scan sample_customer_vllm_logs.csv --discount 0.40
```

### Sample Output Waterfall
```
==============================================================================
⚡ INFERACAP ENTERPRISE LOG SCANNER: CAPACITY & ROI AUDIT REPORT
==============================================================================
📁 Target Telemetry:     sample_customer_vllm_logs.csv
⏱️  Observed Time Window: 71.8 hours (8,028 requests, 1.5M tokens)
------------------------------------------------------------------------------
💰 FINANCIAL RECONCILIATION WATERFALL:
   • Baseline Siloed Spend (On-Demand Peak Provisioning):  $873.81 USD
   • InferaCap Multi-Region Pooled Compute Spend:          $524.29 USD
   ------------------------------------------------------------
   ⭐ NET AVOIDED CASH SPEND (Immediate ROI):              +$349.52 USD
   📈 INVOICE REDUCTION RATE:                              40.0%
   🚀 ANNUALIZED RUN-RATE NET SAVINGS:                    $42,633.98 USD / year
==============================================================================
```

---

## ⚡ Live Ingress: 1-Line Drop-in Replacement

InferaCap is a standard-library, zero-bloat reverse proxy (<40MB RAM footprint). Point your existing client to InferaCap:

```python
import openai

# Drop-in: Point standard OpenAI client to InferaCap Gateway
client = openai.OpenAI(
    base_url="http://127.0.0.1:8765/v1",
    api_key="inferacap-key",
)

response = client.chat.completions.create(
    model="llama-3.1-8b",
    messages=[{"role": "user", "content": "Analyze quarterly financials"}],
    extra_headers={
        "X-Region": "US",
        "X-TTFT-Budget-MS": "250",  # Strict latency SLA budget
    },
)
print(response.choices[0].message.content)
```

---

## 🖥️ Interactive Web UI Dashboard

InferaCap includes an unprivileged localhost dashboard for visual log auditing, real-time fleet health monitoring, and capacity simulation:

```bash
python3 sw004_ui.py --port 8764
# Open in browser: http://127.0.0.1:8764/
```

- **Tab 1: Log Audit Scanner**: Drag & drop CSV/JSON logs to generate visual waterfall reports.
- **Tab 2: Live Gateway & Fleet**: Live Circuit Breakers (`CLOSED` 🟢 / `OPEN` 🔴) and prompt routing tester.
- **Tab 3: Offline Simulator**: Contract-aware reservation solver with multi-scenario comparison.
- **Tab 4: Telemetry Analytics**: Feature interaction tracking and drop/merge optimization ledger.
- **Tab 5: Terminal Video Demo**: Embedded interactive video player.
- **Tab 6: Enterprise Pilot**: 20% Verified Gain-Share agreement calculator.

---

## 🎥 Cinematic Terminal Demo

Experience the full 8-chapter customer journey right in your shell or browser:

```bash
# Run terminal presentation
python3 demo_cli_video.py

# Or open interactive video player in browser
open demo_terminal_video.html
```

---

## 🏛️ Commercial Model & Dual Licensing

InferaCap is distributed under a **commercial dual-licensing architecture**:

1. **Open-Source Evaluation & Diagnostic Suite (Apache 2.0)**:
   - CLI Log Scanner (`inferacap-scan` / `scan_logs.py`), Capacity Simulator, and Python Client SDK (`inferacap.py`) are free and open-source under Apache 2.0.
2. **Commercial Enterprise Gateway Engine (`gateway/`)**:
   - The Live Multi-Region Reverse Proxy, Real-Time SSE Circuit Breaker, and GDPR residency controller are licensed under [`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md).
   - Commercial production deployment requires an active subscription ($499/mo) or a **Risk-Free 20% Verified Gain-Share Pilot** (100% money-back guarantee; you only pay when your cloud GPU bill drops).

### Contact & Enterprise Pilots
* **Founder & Release Lead**: Bhaskar Pandey  
* **Email**: <bhaskarauthor@gmail.com>  
* **Venture Registry**: Independent Research-to-Product Venture (SW-004)  
