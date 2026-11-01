# SW-004 serving load test runbook

28 October 2026 · Client-side harness for an **authorized disposable OpenAI-compatible chat endpoint**. It does not change SW-004's offline, read-only product scope.

## Required inputs before a real benchmark

- Baseline endpoint URL and SW-004 candidate endpoint URL. Both must serve the **same model revision and precision**. Identify whether SW-004 actually controls the candidate serving route; if it does not, label the test as an endpoint reference only.
- Authentication method. Put a bearer token in `SW004_BEARER_TOKEN` in the local shell; never put it in a command, trace, Git, or Drive file. The harness allows HTTP only on localhost when a token is set.
- Approved synthetic workload: target model ID, approximate prompt word count or model-tokenized prompt set, maximum output tokens, arrival rate, concurrency, regions, and cache state. `--synthetic-words` is **not** an exact token count.
- Approved client targets for first-content and end-to-end latency, error rate, throughput/goodput, and the measurement sample plan. Numeric targets are not universal standards.

## Run the paired comparison

Run both endpoints from the **same client machine and region**, with the same command options, seed, model, and synthetic workload. Use a fresh output prefix for every run and record model revision, endpoint region, GPU/engine, server telemetry, and source commit alongside the client JSON. Start with a small smoke run, then test single stream, steady arrival, Poisson arrival, burst, and saturation/failure. Use at least three independent runs for a release comparison; the proposed p99 rule in the main protocol is 1,000 successful requests per critical workload cell, subject to owner approval.

Example smoke command (replace the URL and model with the authorized test endpoint):

```sh
python3.12 qc_serving_load.py \
  --endpoint-url 'https://authorized-test.example/v1/chat/completions' \
  --allow-remote --model 'approved-model-id' \
  --requests 30 --concurrency 1 --arrival single_stream \
  --synthetic-words 128 --max-output-tokens 32 \
  --include-usage --output-prefix 'SW004_SERVING_BASELINE_SMOKE'
```

For a steady load cell, set `--arrival poisson --rate 2 --concurrency 8` and the approved request count. Reuse all those options for the candidate, changing only the endpoint and output prefix. `--first-content-target-ms` and `--e2e-target-ms` together enable SLO goodput once approved; leaving them out records goodput as unknown.

The harness creates `<prefix>.jsonl` with one record per request and `<prefix>.summary.json`. Neither contains prompts, response text, tokens, URLs, or credentials. The endpoint URL is represented by a SHA-256 digest. Keep failures in the denominator. Compare workload and model metadata before comparing results.

## Metric interpretation

The streamed first nonempty content chunk gives **time to first content**, a client-observed TTFT proxy. OpenAI-compatible SSE chunks may contain more than one token; inter-chunk gaps are **not TPOT**. Exact output-token throughput is reported only when the server sends usage. End-to-end latency includes client/server/network effects. The client scheduling-lag distribution helps detect a saturated load generator. Queue wait and GPU utilization need separate server telemetry. Route RTT and payable cost need separate evidence. A local mock passing the harness tests does not establish production serving quality.

Release remains **HOLD** until real endpoint measurements, approved targets, buyer payable cost, rights clearance, and independent review are complete.
