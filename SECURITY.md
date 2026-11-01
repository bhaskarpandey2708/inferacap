# InferaCap Enterprise Security & Architecture Specification

**Canonical Public Whitepaper & Security Due Diligence**  
**Repository:** [github.com/bhaskarpandey2708/inferacap](https://github.com/bhaskarpandey2708/inferacap)  
**Security Point of Contact:** security@inferacap.ai / bhaskarauthor@gmail.com  

---

## 1. Security Architecture & Threat Model

InferaCap is an economically-aware, zero-data-retention, cache-affinity-preserving inference load balancer designed for deployment inside enterprise Kubernetes clusters (VPCs).

### 1.1 In-VPC Boundary Isolation
* **Zero External SaaS Transit:** InferaCap runs entirely within the customer's cloud boundary (AWS EKS, GCP GKE, Azure AKS, or bare-metal). User prompts, tokens, and completions never pass through external vendor servers.
* **Air-Gapped Operation:** InferaCap requires zero outbound connections to external vendor registries or licensing telemetry to route traffic.
* **Non-Root Execution:** The production container runs strictly as non-root POSIX user `10001` (`runAsNonRoot: true`, `readOnlyRootFilesystem: true`, capabilities dropped: `["ALL"]`).

### 1.2 Ephemeral In-Memory Streaming & Zero Token Logging
* **Zero Token Persistence:** InferaCap handles HTTP streaming using asynchronous memory buffers (`asyncio.StreamReader` / `asyncio.StreamWriter`).
* **Zero Disk I/O:** Prompts, completions, embeddings, and weights are NEVER written to disk, local caches, temporary files, or internal databases.
* **Immediate Dereferencing:** Byte chunks forwarded via Server-Sent Events (SSE) are immediately dereferenced for Python garbage collection following socket flushes.
* **Deterministic Metadata Telemetry Only:** Only operational performance metrics are tracked (token counts, TTFT, inter-token latency, HTTP status codes, routing decision timestamps). No customer PII or prompt contents are ever recorded in metrics or logs.

```
                    +-------------------------------------------------------+
                    |                 CUSTOMER VPC BOUNDARY                 |
                    |                                                       |
                    |   +-----------------------------------------------+   |
                    |   |        InferaCap Ingress Gateway Pod          |   |
                    |   |  - Non-root UID 10001 (Distroless / Minimal)  |   |
                    |   |  - Ephemeral in-memory byte streaming         |   |
                    |   |  - Zero prompt/completion disk persistence    |   |
                    |   +-----------------------+-----------------------+   |
                    |                           |                           |
                    |         +-----------------+-----------------+         |
                    |         |                                   |         |
                    |         v (Local Fast-Path)                 v         |
                    |   +--------------------+              +-------------+ |
                    |   | Local vLLM/SGLang  |              | Circuit     | |
                    |   | Cluster (Warm KV)  |              | Breaker     | |
                    |   +--------------------+              +------+------+ |
                    +----------------------------------------------|--------+
                                                                   | Cross-VPC
                                                      (mTLS / TLS 1.3 PrivateLink)
                                                                   v
                                                     +-----------------------------+
                                                     | Off-Peak / Spot GPU Cluster |
                                                     | (EU-West / Kaggle / Asia)   |
                                                     +-----------------------------+
```

---

## 2. KV-Cache & Prefix Caching Preservation

Conventional load balancers break vLLM (PagedAttention) and SGLang (RadixAttention) cache hits by routing multi-turn requests randomly. InferaCap enforces a three-tier affinity guarantee:

1. **Session Affinity (Conversational State):**  
   Requests providing `X-Session-ID`, `X-Conversation-ID`, or OpenAI `user` parameters are consistently pinned to the warm worker holding the active KV-cache tensors for the session TTL (default: 600s).
2. **Prefix-Hash Affinity (System Prompts & Code Repositories):**  
   Prompts sharing identical prefix tokens (e.g. system instructions or RAG contexts) are deterministically routed to the same regional worker group to maximize RadixAttention tree hit rates.
3. **Queue Arbitrage Invariant:**  
   Cross-region routing is prohibited unless local queue latency exceeds the WAN Round-Trip Time plus remote prefill latency:
   $$T_{\text{queue}}^{\text{local}} > RTT_{\text{WAN}} + T_{\text{prefill}}^{\text{remote}}$$

---

## 3. Regulatory Governance & Geo-Fencing

* **GDPR Compliance (Articles 44–49):** InferaCap provides deterministic geo-fencing. Inbound requests tagged with EU residency (`X-Region: EU` or Cloudflare `CF-IPCountry: EU`) are mathematically prevented from routing outside sovereign EU data centers (`residency_permission: false`).
* **HIPAA Compliance:** Because InferaCap stores zero Electronic Protected Health Information (ePHI) and operates inside the customer's VPC, it preserves existing HIPAA controls with zero third-party exposure.
* **SOC2 Type II Alignment:** Compliant with Trust Services Criteria for Security, Availability, Processing Integrity, and Confidentiality.

---

## 4. Resilience & Blast Radius Containment

* **Sub-2ms Routing Overhead:** Asynchronous event loop micro-benchmarks demonstrate $< 1.8\text{ ms}$ (p99) ingress overhead.
* **Autonomous 3-State Circuit Breakers:** Per-backend circuit breakers transition to `OPEN` in $< 50\text{ ms}$ upon detecting 3 consecutive failures or latency timeouts, diverting traffic immediately to healthy local fallbacks.
* **Non-Disruptive Shadow Mode:** Test routing decisions and quantify savings against 100% live traffic without touching production responses.
* **Fail-Open Safe Default:** Internal exceptions automatically default to the local origin cluster, guaranteeing 100% availability.

---

## 5. Security Vulnerability Disclosure

If you discover a potential security vulnerability in InferaCap, please report it via encrypted email to:
* **Email:** `security@inferacap.ai` / `bhaskarauthor@gmail.com`
* **Response SLA:** Acknowledgement within 24 hours; patch and advisory release within 72 hours for critical vulnerabilities.
* Please do not open public GitHub issues for undisclosed security vulnerabilities.
