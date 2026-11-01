# SW-004 performance and quality test record — 27 October 2026

## Scope and evidence

The simulator and T4 model are separate systems. The simulator consumes supplied route latency estimates and makes no model call. Its output is **simulated offline** evidence. The Colab T4 run measures **GPU-local model forward-call** timing for a public reference model; it does not measure client TTFT, production queueing, cross-region RTT, buyer savings, or a SW-004-controlled serving path. All those product claims remain **UNTESTED**.

Parameter definitions, workload axes, and acceptance rules are in `SW004_TEST_PARAMETERS_AND_PROTOCOL.md` and `SW004_TEST_PARAMETERS.json`. Neither a universal serving SLO nor a release PASS is inferred from these measurements.

## Local simulator matrix

In the fresh cloud ops checkout, Python 3.9 and 3.12 each passed all 42 regression tests. The independent finite-grid sweep passed 3,136 cases, including 276 with remote assignments. These checks ran before the publish commit; the simulator source was unchanged from the starting commit.

Command: `python3.12 qc_offline_perf_matrix.py --hours 24,168,744 --regions 2,4,8 --repeats 3 --trace-max-memory`

Environment: macOS 27.0.1, arm64, 6 logical CPUs, Python 3.12. Full raw measurements and scenario/report hashes: `SW004_OFFLINE_PERF_MATRIX_2026-10-27.json`.

| UTC hours | Region/model records | Median runtime, s | Exploratory p95, s | Observations/s at median | Invariants and replay |
| ---: | ---: | ---: | ---: | ---: | --- |
| 24 | 2 | 0.0012 | 0.0013 | 40,127 | PASS |
| 24 | 4 | 0.0060 | 0.0062 | 15,881 | PASS |
| 24 | 8 | 0.0454 | 0.0465 | 4,232 | PASS |
| 168 | 2 | 0.0124 | 0.0139 | 27,132 | PASS |
| 168 | 4 | 0.0453 | 0.0465 | 14,835 | PASS |
| 168 | 8 | 0.2918 | 0.2927 | 4,607 | PASS |
| 744 | 2 | 0.0409 | 0.0417 | 36,398 | PASS |
| 744 | 4 | 0.2150 | 0.2216 | 13,844 | PASS |
| 744 | 8 | 1.5052 | 1.9483 | 3,954 | PASS |

The separate 744-hour, eight-record traced replay peaked at 12.56 MiB of **Python-traced allocation**; this excludes interpreter, native library, and process memory. With only three timing repeats per cell, p95 is the maximum observed repeat and is exploratory. There is no approved machine-independent runtime threshold.

## Colab T4 preflight and smoke

The official Google Colab CLI 0.7.5 assigned an NVIDIA Tesla T4 and released the session after the preflight. Its Python was 3.13.16 with PyTorch 2.11.0+cu130, Transformers 5.20.2, and Hugging Face Hub 1.33.0. The exact preflight output is `SW004_COLAB_T4_PREFLIGHT_2026-10-27.json`.

The smoke used Qwen/Qwen2.5-1.5B-Instruct, Hugging Face revision `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`, model-card license Apache-2.0, FP16, synthetic 128-token input, batch 1, 32 output tokens, one warmup and three measured repetitions. Median prefill forward-call time was 46.653 ms, median decode forward-call step 38.966 ms, median whole-generation rate 24.068 output tokens/s, and peak allocated VRAM 2,996.28 MiB. There were no reported errors. Initial model acquisition/load was 58.514 s and includes Hub fetch; it is not warm serving latency. Full raw values: `SW004_COLAB_T4_SMOKE_2026-10-27.json`.

## Full T4 matrix

Command: `colab run --gpu T4 --timeout 1800 qc_colab_t4.py --prompt-lengths 128,512,1024 --output-tokens 32,128 --batch-sizes 1,2,4 --repeats 3 --warmups 1`. The CLI allocated and released an NVIDIA Tesla T4 with 14,912.69 MiB reported VRAM. The model revision and Apache-2.0 license matched the smoke test. Initial model acquisition/load was 28.664 s, including Hub fetch. All 18 workload cells completed three measured repetitions after one warmup, with zero reported errors or OOMs. Full per-repetition and per-token values: `SW004_COLAB_T4_MATRIX_2026-10-27.json`.

| Input tokens | Batch | Output tokens | Median prefill, ms | Median decode step, ms | Median output tokens/s | Peak allocated VRAM, MiB |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128 | 1 | 32 | 43.397 | 36.452 | 25.966 | 2,996.28 |
| 128 | 1 | 128 | 42.390 | 36.094 | 26.573 | 2,996.28 |
| 128 | 2 | 32 | 44.331 | 37.033 | 50.390 | 3,036.34 |
| 128 | 2 | 128 | 43.449 | 36.129 | 53.052 | 3,036.34 |
| 128 | 4 | 32 | 84.863 | 37.194 | 97.907 | 3,118.53 |
| 128 | 4 | 128 | 88.058 | 36.307 | 104.676 | 3,118.53 |
| 512 | 1 | 32 | 111.504 | 36.266 | 24.072 | 3,118.53 |
| 512 | 1 | 128 | 115.654 | 35.902 | 26.417 | 3,118.53 |
| 512 | 2 | 32 | 242.568 | 36.016 | 44.981 | 3,282.16 |
| 512 | 2 | 128 | 247.815 | 36.343 | 50.678 | 3,282.16 |
| 512 | 4 | 32 | 494.696 | 36.293 | 76.203 | 3,610.42 |
| 512 | 4 | 128 | 482.291 | 36.459 | 96.467 | 3,610.42 |
| 1024 | 1 | 32 | 289.239 | 35.945 | 21.797 | 3,282.16 |
| 1024 | 1 | 128 | 290.113 | 36.163 | 25.565 | 3,282.16 |
| 1024 | 2 | 32 | 591.770 | 36.692 | 35.774 | 3,610.42 |
| 1024 | 2 | 128 | 600.800 | 36.334 | 47.481 | 3,610.42 |
| 1024 | 4 | 32 | 1,182.275 | 40.955 | 50.778 | 4,266.43 |
| 1024 | 4 | 128 | 1,182.100 | 42.003 | 76.993 | 4,266.43 |

The prefill and decode values time synchronized forward calls and include host dispatch and argmax overhead. They are **not** client-observed TTFT or TPOT. The workload is synthetic and has no SW-004 routing decision in the serving path. Three repetitions per cell are a pilot, not a stable tail-latency qualification.

## Release interpretation

Offline simulator correctness and replay passed in the nine measured workload cells. The approved release decision remains **HOLD**. Measured serving latency, model quality on a representative task set, buyer payable cost, rights clearance, and independent release review remain separate gates.
