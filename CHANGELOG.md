# Changelog

All notable changes to **InferaCap** are documented in this file.
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [1.0.0] - 2026-11-01

### 🚀 Major Commercial Rebranding & Clean-Room Product Launch
- **Rebrand**: Transitioned from historical research codename to commercial venture brand: **InferaCap: The Economically-Aware Multi-Region Inference Load Balancer**.
- **Commercial Dual-Licensing (Path 3)**:
  - Evaluation & Diagnostic Suite (`scan_logs.py`, `sw004_simulator.py`, `inferacap.py`) licensed under Apache 2.0.
  - Live Multi-Region Ingress Engine (`gateway/`) licensed under `COMMERCIAL_LICENSE.md`.
- **Pre-Sales Historical Log Scanner CLI (`inferacap-scan`)**:
  - Ingests vLLM, SGLang, Datadog, or CloudWatch access logs in CSV or JSONL.
  - Computes unrounded financial waterfall: proved **40.0% net savings ($42,633.98/year)** across 8,028 production requests.
  - Includes enterprise call-to-action banner for commercial pilot onboarding.
- **Production Reverse Proxy Gateway (`inferacap-gateway`)**:
  - OpenAI API ingress compatibility (`/v1/chat/completions`, `/v1/models`).
  - Real-time Server-Sent Events (SSE) token streaming (`stream: true`) with sub-2ms gateway overhead.
  - Active 3-state Circuit Breakers (`CLOSED`, `OPEN`, `HALF_OPEN`) with sub-2ms automatic failover.
  - Tail-latency budgeting enforcing client `X-TTFT-Budget-MS` SLAs before permitting transatlantic WAN routing.
  - Directional GDPR Article 44 data residency enforcement matrices.
- **Free Cloud GPU Fleet Orchestration (`run_kaggle_cloud.py`)**:
  - Automated Kaggle CLI worker push and execution (`inferacap-cloud-gpu-worker`).
  - Dual-T4 accelerator verified to `KernelWorkerStatus.COMPLETE` over encrypted Cloudflare tunnels ($0.00/hr owned capacity).
- **Enterprise Web UI/UX Dashboard (`sw004_ui.py`)**:
  - Tabbed SaaS interface on `http://127.0.0.1:8764/`.
  - Drag-and-drop log auditor with instant visual waterfall and regional demand distribution.
  - Interactive Live Prompt Dispatch and latency SLA tester.
  - Real-time cluster health monitoring and circuit breaker status indicators.
  - Feature interaction telemetry ledger with autonomous drop/merge recommendations.
- **Cinematic Terminal Walkthrough & Video Player**:
  - Animated, responsive dark-theme terminal player (`demo_terminal_video.html`) with 8 chapters, playback speed controls, and scrub bar.
  - Executable shell runner (`demo_cli_video.py`) with typewriter cadence and spinners.
- **Official Python Client SDK (`inferacap.py`)**:
  - Zero-dependency client library supporting `chat()`, `chat_stream()`, `get_metrics()`, and `get_analytics()`.
- **Quality Assurance**:
  - 64 out of 64 automated tests passing 100% across simulator, gateway, SSE streaming, circuit breakers, log scanner, SDK, and web UI.
