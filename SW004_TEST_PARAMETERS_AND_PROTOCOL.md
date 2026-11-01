# SW-004 test parameters and performance protocol

27 October 2026 · Test contract for the offline, read-only simulator and a separate Colab T4 reference benchmark.

## Evidence boundaries

SW-004 currently makes no model calls and routes no production traffic. Its `estimated_ttft_p95_ms` and `estimated_p95_ms` fields are supplied estimates. A simulator run can check decisions against those estimates, but cannot measure actual TTFT, TPOT, p99, queueing, or cross-region RTT. A Colab T4 run measures one model's local forward-call timing on that runtime; it does not establish buyer savings or serving SLO compliance. Every result must carry one evidence class: **simulated**, **T4 local compute**, **measured serving**, **buyer contract**, or **independent release review**.

[MLPerf Inference rules](https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc) provide useful load patterns and reproducibility practice, including single stream, Poisson server traffic, and offline bulk. SW-004 is not an MLPerf submission and does not inherit model-specific threshold values. [NVIDIA AIPerf metrics](https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference) define client-observed TTFT, inter-token latency, and request latency. [Google SRE](https://sre.google/sre-book/monitoring-distributed-systems/) motivates latency, traffic, errors, and saturation. [OpenTelemetry metric conventions](https://opentelemetry.io/docs/specs/semconv/general/metrics/) guide units and telemetry names. [NIST AI RMF Measure](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/) calls for representative testing, uncertainty, documentation, and independent assessment. [ISO/IEC 25010:2023](https://www.iso.org/standard/78176.html) is a quality model, not a universal numeric performance target.

## Workload and environment axes to freeze

| Axis | Required record |
| --- | --- |
| Source and input | Git commit, schema and algorithm version, input SHA-256, random seed, synthetic/operator/measured provenance and permission. |
| Machine | OS, CPU, RAM, Python, CUDA/driver/PyTorch, GPU and VRAM, model ID/revision/license, precision. |
| Simulator grid | Complete UTC hours 1/24/168/744; region/model records 2/4/8; route graph none/sparse/full/directionally denied. |
| Demand and capacity | Zero, flat, skew, staggered peaks, simultaneous peaks, surge, outage; whole-GPU capacity, utilization, reserve. |
| Routing and latency | Residency and model compatibility; supplied TTFT/E2E estimates just below/equal/above budget; egress and failover. |
| Economics | On-demand price windows, fixed commitments, owned capacity, software, operations, migration, payable invoice delta. |
| T4 reference | Qwen/Qwen2.5-1.5B-Instruct (Apache-2.0), FP16, synthetic prompt tokens 128/512/1024, output tokens 32/128, batch 1/2/4. |
| Future serving | Exact prompt/output distribution, cold/warm cache, arrival process, concurrency, origin/destination, duration, errors, trace schema. |
| Acceptance | Product owner approved TTFT, TPOT, E2E p95/p99, error and goodput targets per workload class before comparison. |

## Parameter register and quality checks

`SW004_TEST_PARAMETERS.json` is the machine-readable register of 49 metrics, with unit, evidence class, availability, and target. Decision-critical groups are:

| Group | Required checks | Current evidence |
| --- | --- | --- |
| Input and numerical correctness | Strict schema and complete UTC grid; demand conservation; whole-GPU capacity; residency/model/route eligibility; estimated latency boundary; lower bound ≤ candidate; exact invoice/net cash reconciliation; zero/negative/infeasible cases; deterministic replay. | Regression suite, finite-grid sweep, synthetic stress and new runtime matrix. |
| Offline performance | Wall runtime by grid size, median/exploratory p95, observations/s, report bytes, step-cap/errors, separate traced Python peak memory. | `qc_offline_perf_matrix.py`; no machine-independent threshold approved. |
| T4 model compute | Initial model acquisition/load time including Hub fetch; synchronized prefill and per-token decode forward-call time; generation throughput; peak allocated/reserved VRAM; OOM/errors; hardware/software/model fingerprint. | `qc_colab_t4_preflight.py` and `qc_colab_t4.py`; actual T4 required. |
| Measured serving | Client-observed first-content (TTFT proxy), exact TTFT/TPOT when token events support them, E2E p50/p90/p95/p99; requests/s, output tokens/s where usage is reported, SLO goodput, queue wait, timeout/error rate, client scheduling lag, GPU utilization/memory. | `qc_serving_load.py` is ready for an authorized endpoint; real serving remains UNTESTED. |
| Route/resilience | Origin→destination RTT, egress, failover, saturation, network degradation, forbidden route and data leakage. | Synthetic routing checks only; real network UNTESTED. |
| Model quality | Task accuracy and output-length parity versus fixed reference under engine/precision changes. | UNTESTED pending representative dataset and tolerance. |
| Commercial and energy | Payable invoice delta, fixed commitment invariance, egress/ops/software/migration, cost per success/token, energy if instrumented, uncertainty. | Synthetic arithmetic only; buyer contract and power telemetry UNTESTED. |
| Security, privacy, rights | Input limits, secrets and PII handling, source rights, independent review, failure containment. | Developer checks only; independent release review UNTESTED. |

## Execution and acceptance protocol

1. Record exact source revision, input hashes, environment, and commands. Run Python 3.9/3.12 regression suites, finite-grid sweep, CI smoke, and 744-hour stress. Check cloud files for `UF_DATALESS` and hydrate before batch reads.
2. Run 2/4/8 region-model records × 24/168/744 hours with a warmup and at least three untraced repeats. Preserve every time, median, exploratory p95, observations/s, output size, invariant checks, and replay equality. Trace memory in a separate run; it changes timing. Do not infer a universal runtime PASS from one machine.
3. Request T4 with the [official Colab CLI](https://github.com/googlecolab/google-colab-cli/blob/main/README.md), verify actual GPU identity, model revision and license, then measure synthetic tokens with warmups and repetitions. Stop the runtime after the test. [Colab free GPU types and limits vary](https://research.google.com/colaboratory/faq.html); report unavailable if no T4 is assigned. Never silently substitute another accelerator.
4. For serving qualification, use an authorized endpoint and the same model/precision/workload on baseline and candidate. Test single stream, steady Poisson, burst, saturation and failure. Record raw per-request timestamps, input/output token counts, errors, and route without prompts or personal identifiers. Keep failures in the denominator and separate client latency from server compute. A proposed project rule is at least 1,000 successful requests per critical p99 cell, three independent runs, and uncertainty intervals. Smaller T4 pilots are exploratory; the owner must approve actual sample plan and SLO.
5. PASS only a metric with correct evidence class, frozen target, representative workload, and reviewer. Mark UNTESTED when endpoint, dataset, contract, rights grant, telemetry, trace, or target is absent. Capacity/residency violation, accounting mismatch, missing rights, or private-data exposure is release HOLD. Synthetic route estimates never become measured inference claims.

## Starting point and result record

The existing Python 3.9 and 3.12 suites each passed 42 tests at starting commit `dd45a3735ef7ffd206d89f3436ec5753fa4238c1`. The approved Sprint 1 release decision remains HOLD. Current measured pilot results and raw JSON are in `SW004_TEST_RESULTS_2026-10-27.md` and companion files. This protocol opens a measurement lane; it does not change the release decision.
