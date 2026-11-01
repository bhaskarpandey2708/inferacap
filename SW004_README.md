# SW-004: InferaCap Inference Optimization & Load Balancer

InferaCap is **The Economically-Aware Multi-Region Inference Load Balancer**.
It federates multi-region LLM serving infrastructure (vLLM, SGLang, Ollama, Kaggle Dual-T4/P100 GPU clusters, AWS/GCP) behind an intelligent OpenAI-compatible reverse proxy that routes live inference requests according to cloud contracts, idle reservations, data residency laws (e.g. GDPR), and TTFT latency SLAs.

It also retains the complete offline analytical engine as the **Pre-Sales Free Trial Simulator**, allowing prospective enterprise customers to analyze historical logs, calculate dollar savings, and click **"⚡ Enable Live Routing"** to activate InferaCap.

## Quickstart & Demos

```sh
# 1-Command Interactive Live Demo (Starts 3 regional clusters, InferaCap Gateway & Web UI, runs 5 live routing scenarios)
python3 demo_inferacap.py

# InferaCap Live Online Inference Gateway (Standalone)
python3 run_gateway.py gateway/sample_gateway_config.json --port 8765

# Launch Kaggle Cloud GPU Worker (Turnkey OpenAI node on Kaggle dual-T4 with Cloudflare Tunnel)
python3 gateway/inferacap_kaggle_worker.py --port 8000 --region KAGGLE

# Run Unit & Integration Tests (58 tests covering Engine, UI, Gateway, Dynamic Nodes, Scanner, and Sensitivity)
PYTHONPATH=. python3 -m unittest -v test_sw004_simulator test_sw004_ui test_sw004_sensitivity test_live_gateway test_kaggle_worker test_scan_logs

# Offline Pre-Sales Economics Simulator & Reports
python3 sw004_simulator.py sw004_sample_scenario.json report.json --report-csv report.csv
python3 sw004_ui.py
```

The browser UI opens at `http://127.0.0.1:8764/`. It binds only to loopback, runs in memory, limits request size, and times out stalled local connections after 10 seconds. Up to eight local requests can run concurrently; excess connections receive HTTP 503, so one slow peer cannot block `/health`. An analyst can load, edit and save a scenario, run it, inspect summary results, and download dated JSON/CSV reports. The CLI commands also write dated JSON and optional CSV reports. Every scenario JSON must declare `schema_version: 1`; unsupported, missing, boolean or string versions fail validation. Reports export this input schema version separately from the engine version. The CSV input must have the canonical header documented in `sw004_sample_observations.csv`, including `scenario_id`, with one explicit row for every region/model/hour. `scenario_sha256` identifies the exact parsed input; equivalent numeric values encoded with different JSON types can have different hashes. `status=FEASIBLE_HEURISTIC` means the route assignments meet encoded capacity, permission, and estimated TTFT and end-to-end p95 constraints; it does not prove measured SLA compliance, global optimality, or a real customer invoice saving. All inputs in the samples are synthetic.

## Supported scope

- Two to eight region/model capacity records and at most 31 days of explicit UTC hourly observations.
- Prototype input bounds: nonnegative integers at most 1,000,000,000; nonzero decimal values from 0.000001 through 1,000,000,000 with at most 18 significant digits; provenance references at most 1,024 printable characters. Out-of-range inputs fail with a named validation error.
- Region/model labels and provenance references must be printable; control and bidirectional formatting characters fail validation before they can enter JSON/CSV reports.
- USD hourly on-demand GPU spend, noncancellable GPU reservations and owned GPU capacity, with explicit provenance. Owned records require `owned_gpus=capacity_gpus`, omit `committed_gpus`, and set `price_usd_gpu_hour=0`; operational reserve remains unavailable. Owned hardware purchase/depreciation and future procurement avoidance are excluded from current cash, while incremental power or operations must be entered as added costs.
- Noncancellable reservations have a fixed committed GPU rate and a separate marginal overflow rate. Actual operator-supplied or measured reservation inputs must provide the overflow rate, matching region, and UTC contract window covering the scenario. Synthetic examples may omit these terms; the report labels the same-rate and scenario-window assumptions.
- Flat actual operator-supplied or measured on-demand prices require `price_start_utc` and `price_end_utc` covering the full scenario. Synthetic flat prices may omit both dates; reports label the assumed scenario-wide window. For mid-scenario changes, omit the flat price/date fields and supply `on_demand_price_windows`: an ordered, contiguous list of UTC windows covering the scenario. Each window needs `start_utc`, `end_utc`, `price_usd_gpu_hour`, `source_kind`, and `source_ref`. The report exports the window rate and provenance in JSON and CSV, and the engine prices each hour under its active window. Reservation rate changes and cancellation still require separate scenarios and contract review.
- JSON, CSV and browser reports expose exact fixed reservation and variable usage invoice components for both baseline and candidate. Variable usage includes on-demand GPUs and GPUs above a reservation; exact components add to compute totals before cent display rounding.
- JSON/CSV reports include the explicit scenario start/end UTC, per-region billing terms, and each origin-hour's TTFT and end-to-end budgets beside route latency estimates. Region/model labels that would collide in report keys are rejected.
- Ordered, permitted origin to destination routes with source references, required estimated TTFT p95 and end-to-end p95 values, egress and capacity checks. Both route estimates must meet each origin-hour budget; absent TTFT estimates fail validation. JSON/CSV reports export the checked route latency terms.
- Whole-GPU baseline and deterministic positive-gain transfers that check one-GPU source reductions, all remaining local origin demand, destination capacity, and paid commitment boundaries. This remains a heuristic. A 10,000-transfer cap rejects excessive workloads without a partial report. Reports include a cost waterfall, route assignments, and zero or negative net cash deltas. Displayed USD components are rounded to cents; a signed rounding-adjustment line reconciles them to the independently rounded exact net result.
- A perfect-pooling compute lower bound that retains fixed reservation invoices, removes route restrictions, and allows fractional incremental GPUs. It is a bound on compute cost, not an achievable routing plan or net cash forecast. The report also separates required GPU-hours from invoice savings.
- Explicit errors for malformed, duplicate, missing or infeasible inputs.
- JSON file, HTTP and browser-run inputs reject duplicate object keys, including nested keys, and nonstandard `NaN`/`Infinity` literals. The browser sends the original scenario text to the local parser before any calculation.
- Unknown scenario, region, observation, route and contract fields fail validation; unsupported terms cannot silently change the interpretation of an invoice or route.
- CSV observation parsing and formula-safe CSV cost, assignment, transfer, and provenance export.
- Local browser form with fixed sample loading, bounded inputs, same-origin session token, no server-side scenario storage, and report downloads.

## Input contract and product proposal mapping

The normative offline input for the current engine is the `schema_version: 1` JSON shown in `sw004_sample_scenario.json`, or `sw004_sample_config.json` plus the canonical observations CSV. The earlier product proposal used some different names and included capabilities that are still open. Do not silently substitute those proposed fields into version 1: unknown fields fail validation.

| Proposed concept | Version 1 input | Boundary |
| --- | --- | --- |
| Scenario ID, schema version, currency | `scenario_id`, integer `schema_version: 1`, `currency: "USD"` | Other currencies and versions fail. |
| Period start, end, expected hours | UTC `start_utc` and `hours` (1–744) | End is derived as start plus hours and exported; every region/model/hour observation is required. |
| Region, model and compatible GPU type | One `regions` record per `(region, model)` | Exact model-string matching only; heterogeneous GPU types and a separate model catalog are unsupported. |
| Purchased GPUs, operational reserve, effective throughput | `capacity_gpus`, `reserve_gpus`, `requests_per_gpu_hour`, `max_utilization` | Usable supply is capacity minus reserve; effective request capacity is throughput times utilization. `capacity_gpus` is a supply limit, not proof of a purchased or cancellable invoice. |
| Billing type and rate | `billing_type`, `price_usd_gpu_hour`, optional `overflow_price_usd_gpu_hour`, `committed_gpus` or `owned_gpus`, plus required actual-source dates | On-demand, noncancellable reservation and owned are supported. Scheduled on-demand prices use `on_demand_price_windows`. Cancellable reservations, mixed owned/rented records, mid-period reservation changes and fungible commitments are unsupported. |
| Ordered route permission and network cost | `allowed_routes` with origin, destination, model, `residency_permission`, estimated TTFT/end-to-end p95, bytes and egress rate | Route permission is explicit and directional. Estimates are checked against each origin-hour budget; they are not measured SLA proof. |
| Hourly workload and latency limits | `observations` or the canonical CSV, one row per region/model/hour | UTC hours, request counts, token means, TTFT/end-to-end budgets and provenance are validated. |
| Other current-period costs and uncertainty | `software_usd`, `operations_usd`, `migration_usd`; 2–10 complete scenarios for sensitivity | Costs apply to the whole scenario. The sensitivity range covers supplied cases only; it is not a statistical confidence interval. |

Every capacity, observation, route and scheduled-price record carries `source_kind` and `source_ref`. A version 1 input does not grant permission to use operator data; that remains a separate owner decision. Product acceptance of this bounded contract and any change to the earlier proposal is pending Bhaskar's review.

The benchmark repeats the bundled synthetic daily pattern for 720 hours, extends its price and reservation windows to cover that period, and runs the same 2,160-row scenario ten times. It checks complete report equality and records elapsed time and peak Python traced memory. This checks one synthetic workload on the machine used to run it; it is not a latency, scalability, or customer-data guarantee.

For sensitivity analysis, supply two to ten complete scenario JSON files with the same currency, UTC period and region/model keys. The comparison report records each input hash and cost waterfall, then names the minimum and maximum net results and flags any nonpositive case. Change explicit demand, prices, routes or added costs in separate files to examine their effect. The displayed range covers only the supplied cases; it is not a statistical confidence interval or evidence that a customer can realize the savings.
The `--example` command compares the bundled synthetic case with the same case at a $1,000 software cost. For your own cases, run `python3 sw004_sensitivity.py sensitivity.json base.json downside.json`. The browser UI also accepts 2–10 full scenario JSON files, displays each modeled net result and its range, and downloads the comparison JSON.

## Limitations and next work

The prototype does not handle mixed owned/rented capacity in one region/model record, mid-scenario reservation changes or cancellations, globally fungible commitments, heterogeneous GPU types, shared model capacity, exact global optimization, measured p95/p99 proof, or customer contract validation. `price_usd_gpu_hour` is the fixed reservation rate for a reserved record and the marginal rate for a flat on-demand record; scheduled on-demand windows supply their own hourly rates. `overflow_price_usd_gpu_hour` is the separately billable marginal rate above a reservation. Route TTFT and end-to-end p95 estimates are checked against budgets but must not be presented as SLA guarantees. The report keeps those limitations visible. Independent QA and human review are required before any release claim.
