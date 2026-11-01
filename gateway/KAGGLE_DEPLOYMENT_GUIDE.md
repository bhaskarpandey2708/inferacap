# ⚡ InferaCap: Kaggle Cloud GPU Worker Deployment Guide

This guide describes how to deploy an autonomous **InferaCap Cloud GPU Worker** on Kaggle's free GPU infrastructure (Dual NVIDIA Tesla T4 or P100) and federate it into the **InferaCap Live Intelligent Load Balancer**.

---

## 1. Value Proposition & Economics

| Dimension | Standard Cloud On-Demand (AWS/GCP) | Kaggle Cloud Worker Federated via InferaCap |
| :--- | :--- | :--- |
| **GPU Hardware** | 1x NVIDIA T4 (16GB) | **2x NVIDIA T4 (32GB Total VRAM)** |
| **Hourly Compute Cost** | ~$0.90 – $1.20 / GPU-hour | **$0.00 / hour (Free Quota)** |
| **Marginal Request Cost** | Paid per on-demand compute minute | **$0.00 (Zero Marginal Cost)** |
| **InferaCap Billing Tier** | `on_demand` | **`owned`** |
| **Role in Federation** | Expensive overflow destination | **Primary zero-cost sink for cross-region burst traffic** |

> [!TIP]
> Each Kaggle account provides 30 hours of free dual-GPU compute per week (60 T4-GPU hours). Federating one or more worker nodes eliminates peak surge on-demand spending during heavy processing windows.

---

## 2. Included Deliverables

In [`gateway/`](file:///Users/bhaskarpandey/Library/CloudStorage/GoogleDrive-bhaskarauthor@gmail.com/My Drive/Independent Research-to-Product Venture/01 - Venture Projects/SW-004 - SkyWalker AI Inference Optimization/04 - Simulator Development & Testing/skywalker-simulator/gateway/):
- [`inferacap_kaggle_worker.py`](file:///Users/bhaskarpandey/Library/CloudStorage/GoogleDrive-bhaskarauthor@gmail.com/My Drive/Independent Research-to-Product Venture/01 - Venture Projects/SW-004 - SkyWalker AI Inference Optimization/04 - Simulator Development & Testing/skywalker-simulator/gateway/inferacap_kaggle_worker.py): Autonomous OpenAI-compatible serving daemon with built-in hardware detection and Cloudflare tunnel orchestration.
- [`inferacap_kaggle_notebook.ipynb`](file:///Users/bhaskarpandey/Library/CloudStorage/GoogleDrive-bhaskarauthor@gmail.com/My Drive/Independent Research-to-Product Venture/01 - Venture Projects/SW-004 - SkyWalker AI Inference Optimization/04 - Simulator Development & Testing/skywalker-simulator/gateway/inferacap_kaggle_notebook.ipynb): Turnkey Jupyter Notebook with 1-click execution cells.
- [`kernel-metadata.json`](file:///Users/bhaskarpandey/Library/CloudStorage/GoogleDrive-bhaskarauthor@gmail.com/My Drive/Independent Research-to-Product Venture/01 - Venture Projects/SW-004 - SkyWalker AI Inference Optimization/04 - Simulator Development & Testing/skywalker-simulator/gateway/kernel-metadata.json): Deployment metadata for automated Kaggle CLI pushes.

---

## 3. Deployment Options

### Method A: Kaggle Web UI (1-Click Import)
1. Open [kaggle.com/code](https://www.kaggle.com/code) and click **"New Notebook"**.
2. Click **File** -> **Import Notebook** -> Select [`inferacap_kaggle_notebook.ipynb`](file:///Users/bhaskarpandey/Library/CloudStorage/GoogleDrive-bhaskarauthor@gmail.com/My Drive/Independent Research-to-Product Venture/01 - Venture Projects/SW-004 - SkyWalker AI Inference Optimization/04 - Simulator Development & Testing/skywalker-simulator/gateway/inferacap_kaggle_notebook.ipynb).
3. In the right-hand **Notebook Options** panel:
   - **Accelerator**: Select **GPU T4 x 2** (or GPU P100).
   - **Internet**: Ensure **Internet On** is checked.
4. Click **"Run All"**.
5. Copy the generated `https://[subdomain].trycloudflare.com` URL printed in the output of Step 4.

---

### Method B: Automated Kaggle CLI Push
If the Kaggle CLI is authenticated locally:
```bash
cd "04 - Simulator Development & Testing/skywalker-simulator/gateway"

# 1. Update kernel-metadata.json id with your Kaggle username:
#    "id": "<your-kaggle-username>/inferacap-cloud-gpu-worker"

# 2. Push notebook directly to Kaggle
kaggle kernels push -p .

# 3. Track execution status
kaggle kernels status <your-kaggle-username>/inferacap-cloud-gpu-worker
```

---

### Method C: Standalone Worker Script (Any Remote Linux/Cloud GPU)
The worker script runs on Kaggle, Google Colab, RunPod, Lambda Labs, or local bare-metal:
```bash
# Basic run with automatic Cloudflare Tunnel
python3 inferacap_kaggle_worker.py --port 8000 --region KAGGLE

# With automatic self-registration into your running InferaCap Gateway:
python3 inferacap_kaggle_worker.py \
  --port 8000 \
  --region KAGGLE \
  --capacity 8 \
  --gateway-url http://your-inferacap-gateway:8765
```

---

## 4. Connecting the Worker to InferaCap

### Dynamic Self-Registration (Zero Restart)
If your InferaCap gateway is running on an accessible endpoint:
```bash
curl -X POST http://127.0.0.1:8765/v1/nodes/register \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "kaggle-t4-worker-01",
    "provider": "kaggle",
    "region": "KAGGLE",
    "base_url": "https://random-assigned-domain.trycloudflare.com",
    "gpu_type": "T4",
    "gpu_count": 2,
    "models": ["llama-3.1-8b", "qwen2.5-coder", "mistral-7b-instruct"],
    "capacity": 8,
    "billing_type": "owned",
    "hourly_cost_usd": 0.00,
    "estimated_rtt_ms": 75.0
  }'
```
The InferaCap live router immediately binds the node, registers bidirectional routing rules, and starts directing burst traffic to it.

### Static Configuration via `sample_gateway_config.json`
Add the `KAGGLE` region block directly into `gateway/sample_gateway_config.json`:
```json
{
  "regions": {
    "KAGGLE": {
      "backends": ["https://random-assigned-domain.trycloudflare.com"],
      "models": ["llama-3.1-8b", "qwen2.5-coder", "mistral-7b-instruct"],
      "capacity_concurrent_requests": 8,
      "billing_type": "owned",
      "on_demand_rate_gpu_hour": 0.00,
      "committed_gpus": 2,
      "overflow_rate_gpu_hour": 0.00,
      "requests_per_gpu_hour": 3600.0
    }
  },
  "allowed_routes": [
    {
      "origin_region": "US",
      "destination_region": "KAGGLE",
      "model": "*",
      "residency_permission": true,
      "estimated_rtt_ms": 75.0,
      "max_allowed_ttft_ms": 400.0,
      "egress_cost_per_gb": 0.01
    }
  ]
}
```

---

## 5. Verification Commands

```bash
# 1. Health Probe
curl -i https://[subdomain].trycloudflare.com/health

# 2. Inspect Supported Models
curl -i https://[subdomain].trycloudflare.com/v1/models

# 3. Test OpenAI Chat Completion
curl -i -X POST https://[subdomain].trycloudflare.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama-3.1-8b",
    "messages": [{"role": "user", "content": "Federated inference test"}]
  }'
```
