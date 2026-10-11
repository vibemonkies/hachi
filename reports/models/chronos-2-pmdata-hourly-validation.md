# Chronos-2 zero-shot vs #9 comparators: PMData hourly heart rate, validation folds (#10)

Aggregate results only. The report contains no participant ids, rows or predictions. The machine-readable summary is [`chronos-2-pmdata-hourly-validation.json`](chronos-2-pmdata-hourly-validation.json). Per-participant packets stay in approved storage (see the last section).

**What this is:** one zero-shot pretrained forecaster scored on the inner validation folds of the frozen #7/#9 PMData protocol. The comparison is paired: same splits, same cutoffs, same targets.

**What it is not:** a held-out test result. The protocol's outer test fold stays sealed. It is also not a claim about Apple Watch data, illness, or any population beyond these 12 PMData participants over one week.

## Identity

| | |
|---|---|
| Code | `issue-10-chronos` at `2ec1b48d2e36fe8425d3f1b30df910038c341b4c`, clean tree. It includes main `bca82fd` (PR #54 protocol runner). |
| Protocol | `configs/evaluation/pmdata-hourly-validation.json`, `document_sha256` `2adbe991611b949f2a99877422e5836f86540f00ee8961db83128ca554134bd7`. Bound by hash in `configs/models/chronos/pmdata-hourly-hr.json` (config `document_sha256` `34eaf607c60c5fd3ed65b5325ba14cb157e7df7b17f1d4bc9aee5ee5cf497b64`). |
| Dataset | PMData snapshot `pmdata` / `simula-2020-04-24` / `06606ac2708b1c5329b1cfa04e6edfb9a0583c5a6c9f2eb1465b07aebab2ee47`, verified at load |
| Splits | Nested plan `document_sha256` `df6fd2b36daf9514b7e2e1c16eb32de414c65712601371a9e08fc0b17b741c06`. Active outer fold 0 (4 test participants, sealed: `test_opened_at_utc = null`). Inner validation splits `13a312b2…`, `4b63051a…`, `f385983f…`, built by the shared `pmdata_run.fold_split`. |
| Checkpoint | `amazon/chronos-2` revision `29ec3766d36d6f73f0696f85560a422f50e8498c`, Apache-2.0. `model.safetensors` sha256 `ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42`, checked before loading. |
| GPU runtime | GX10 `5ASB`, NVIDIA GB10 (sm_121), driver 580.142. Pinned lock `infra/gx10/requirements.lock` sha256 `8e30ab7405c3087d73bc489dbdcb3912cba2298f1a2fd4b7fda57b1548ab5f8a`: torch 2.8.0+cu129, chronos-forecasting 2.3.2, transformers 4.57.6. float32, batch 256, `cross_learning=False`. |
| CPU runtime | Justin's Mac (macOS 26.6.2, arm64), Python 3.12.13, `uv.lock` sha256 `2fa7fc3ccb8453e5403a2aebe00ef7b8176f2a281e2ffd3546928b892a65f8bc` |
| Requests → forecasts | 77 distinct 48 h contexts, `requests.jsonl` sha256 `bacf077badbed44ff1348327fefdd5ea193164922c95d4f70dd52409ff5788e2`. `predictions.jsonl` sha256 `e306ee985b39fc72ee4fb6ce3138a6de7388130638699ba331d88fb56b24c3d3`, 24 steps × 21 quantiles each. GX10 job `issue10-20261011T110443Z-infer`, via `scripts/gx10/gpu-run`, exit 0, 8.0 s. |

Commands are in [`src/hachi/models/chronos/README.md`](../../src/hachi/models/chronos/README.md).

## Cross-check against the #9 runner

SnowyFortress's independent #9 run, from clean `bca82fd` on Ezzy's Mac, published its packet hashes in `reports/evaluation/pmdata-hourly-validation/packet-index.json` (`issue-7-ezzy-integration` at `f048f15`). This run refits the same four comparators inside `compare_forecasts`. Against that index:

- **Comparators:** all 12 comparator `evaluation.json` hashes are identical byte for byte (3 folds × 4 models).
- **Splits:** all 3 `split.json` hashes are identical.
- **Origin plans:** all 24 `origins.json` files match, covering both the comparator side and the Chronos side of every comparison. Chronos was therefore scored on exactly the same origins, cutoffs and target hours as the published baselines.

## How causality is kept

- **Export.** The #7 harness ran with **no labels**. Each predictor call was recorded as the context it would receive: hourly HR means available by the cutoff, 48 h ending at the cutoff, absent hours null.
- **GX10.** It received only those contexts and a horizon. No subject id, cutoff, target or label was sent.
- **Scoring.** The harness ran again. Each forecast was looked up by the content hash of the context the harness rebuilt, and a context the export did not produce fails the run.
- **Covariates.** None, so measured physiology never enters as a known future covariate. Raw observations and other channels are refused by the adapter.
- **Selection.** Chronos is zero-shot. No hyperparameter, interval level or threshold was tuned on these folds. The 48 h context is the protocol's lookback, and the 80% interval was fixed in the committed config before the run.

## Cohort and coverage

- **Participants:** 12 validation participants, pooled from 3 disjoint inner folds of 4.
- **Schedule:** daily cutoffs at 00:00 UTC, 1–7 Jan 2020, with a 24 h horizon. That is 84 planned origins and 2,016 target hours.
- **Origins:** 7 origins (168 target hours) were excluded for insufficient history (< 24 observed hours in the 48 h lookback). Every model shares that exclusion.
- **Labels:** 249 target hours have no eligible label (coverage < 0.5 or < 30 samples).
- **Feature view:** 46,406 HR-mean bins included, 8,593 empty; the protocol's quality rules dropped none.
- **Chronos coverage:** it forecast all 77 remaining origins and abstained on none. The tree abstained on 118 labelled target hours and seasonal-naive on 135. Paired metrics use only the targets both models predicted; each model's own row below uses everything it predicted.
- **Adapter adjustments:** 19 raw upper quantiles above the registered 300 bpm bound were clipped. No quantiles crossed, so none were rearranged.

## Results

Equal participant weighting. 95% intervals are participant-level bootstrap (1,000 resamples, seed 42). Units are bpm.

### Each model on its own predictions

| Model | Scored points | Abstained | MAE | RMSE | Interval coverage (80%) | Interval width |
|---|---:|---:|---|---|---|---|
| Chronos-2 zero-shot | 1,599 | 0 | 8.94 (7.69 to 10.17) | 14.01 (11.97 to 15.97) | 0.812 (0.779 to 0.846) | 29.42 (26.48 to 32.65) |
| Last valid | 1,599 | 0 | 12.03 (10.94 to 13.01) | 17.21 (15.14 to 19.17) | — | — |
| Seasonal naive (24 h UTC) | 1,464 | 135 | 11.15 (9.42 to 12.94) | 17.11 (14.56 to 19.73) | — | — |
| Train population mean | 1,599 | 0 | 12.20 (10.27 to 14.19) | 16.14 (13.94 to 18.39) | — | — |
| Causal tree | 1,481 | 118 | 10.32 (9.38 to 11.30) | 14.39 (12.98 to 15.85) | — | — |

### Paired differences (Chronos minus comparator; negative favours Chronos)

| Chronos minus | Paired points | ΔMAE | ΔRMSE | Participants where Chronos MAE is lower / higher | Per-participant ΔMAE min / median / max |
|---|---:|---|---|---|---|
| Last valid | 1,599 | −3.09 (−4.28 to −2.06) | −3.20 (−4.49 to −2.16) | 12 / 0 | −7.15 / −2.60 / −0.49 |
| Seasonal naive (24 h UTC) | 1,464 | −2.24 (−3.02 to −1.52) | −3.01 (−4.06 to −2.12) | 12 / 0 | −4.74 / −1.87 / −0.06 |
| Train population mean | 1,599 | −3.26 (−4.78 to −1.93) | −2.12 (−3.56 to −0.96) | 12 / 0 | −7.24 / −1.72 / −0.34 |
| Causal tree | 1,481 | −1.29 (−2.64 to −0.06) | −0.26 (−1.87 to 0.96) | 9 / 3 | −7.52 / −0.96 / +2.89 |

Per-fold ΔMAE vs the tree is +0.18, −3.30 and −0.76 for inner folds 0, 1 and 2. The other three comparators are favoured in no fold.

### Quantile loss

Mean pinball loss over deciles 0.1–0.9, on the same paired targets. The comparators issue point forecasts, scored as degenerate distributions, so their loss equals MAE / 2. Part of Chronos's advantage here is simply that it states its uncertainty.

| Chronos vs | Comparator | Chronos | Difference |
|---|---|---|---|
| Last valid | 6.01 (5.47 to 6.51) | 3.61 (3.08 to 4.11) | −2.41 (−2.95 to −1.96) |
| Seasonal naive (24 h UTC) | 5.58 (4.71 to 6.47) | 3.61 (3.08 to 4.10) | −1.97 (−2.42 to −1.54) |
| Train population mean | 6.10 (5.13 to 7.10) | 3.61 (3.08 to 4.11) | −2.49 (−3.21 to −1.77) |
| Causal tree | 5.16 (4.69 to 5.65) | 3.64 (3.13 to 4.14) | −1.53 (−2.22 to −0.95) |

### Chronos interval calibration (all 1,599 scored targets)

| Nominal central interval | Observed coverage |
|---|---|
| 50% (q0.25–q0.75) | 0.514 (0.481 to 0.547) |
| 80% (q0.1–q0.9) | 0.812 (0.779 to 0.846) |
| 90% (q0.05–q0.95) | 0.920 (0.897 to 0.943) |
| 98% (q0.01–q0.99) | 0.990 (0.982 to 0.996) |

### Latency and memory

The two sides ran on different hardware, so compare orders of magnitude, not ratios. Comparator timings come from the scoring pass. Their memory figures are traced Python/NumPy allocations in a separate pass, so tracing overhead stays out of the timings.

| Model | Where | Fit (mean per fold) | Predict per origin, p50 / p95 | Peak memory |
|---|---|---|---|---|
| Chronos-2 zero-shot | GX10 GB10 GPU | none (zero-shot); model load 4.2 s | single request 14.6 / 14.8 ms; batched 77 contexts in 0.16 s (2.0 ms each) | CUDA allocated 0.45 GiB (single), 0.47 GiB (batched); reserved 0.49 GiB; process RSS 1.54 GiB |
| Last valid | Mac CPU | 0.13 s | 0.14 / 0.37 ms | fit 11.1 MiB, predict 14 KiB |
| Seasonal naive | Mac CPU | 0.27 s | 0.18 / 0.43 ms | fit 11.1 MiB, predict 21 KiB |
| Train population mean | Mac CPU | 0.12 s | 0.01 / 0.02 ms | fit 11.1 MiB, predict 0.7 KiB |
| Causal tree | Mac CPU | 3.12 s | 3.3 / 7.1 ms | fit 63.2 MiB, predict 26 KiB |

GB10 memory is unified, so allocator peaks do not cover all device memory. End-to-end run times were 21 s for the CPU export, 8 s for the GX10 job, and 368 s for the CPU score (0.57 GB RSS), which includes the traced memory pass.

## Negative results and limitations

- **No reliable RMSE gain over the tree.** ΔRMSE is −0.26 bpm (−1.87 to 0.96). The MAE gain over the tree is marginal: its upper bound is −0.06 bpm. Chronos was worse than the tree for 3 of 12 participants (up to +2.89 bpm) and in inner fold 0.
- **Large errors persist.** Chronos's RMSE (14.0) is far above its MAE (8.9), so occasional large misses remain, likely activity bursts no model sees coming from HR history alone.
- **Small sample.** 12 participants, one week (1–7 Jan 2020), 77 origins. The intervals are wide, and this is validation-fold evidence only. The sealed outer test (4 participants) has not been opened. Any promotion decision must follow the protocol's selection and test steps.
- **Context is protocol-limited.** The context is the protocol's 48 h lookback. Chronos-2 accepts up to 8192 h; longer context was not tried, because that would be selection on these folds.
- **Pretraining overlap unknown.** Chronos-2's corpus is not enumerated against PMData. `pretrained_cohort_overlap = "unknown"`.
- **Calibration scope.** It is measured here on the same validation targets, so the 80% interval is labelled `uncalibrated` for product use until held-out coverage is measured.
- **Assumed clocks.** PMData clock mapping and historical availability are documented assumptions (#5), not observed synchronization.
- **Univariate only.** Steps, sleep and other channels were not offered to the model. Multivariate and past-covariate variants are untested.

## Approved storage

| Copy | Location |
|---|---|
| Justin's T7 | `/Volumes/T7/Stockpile/hachi.datasets/runs/justin06lee/issue10-20261011T110443Z/` (`export/`, `gx10/`, `score/`) |
| GX10, inference | `~/hachi/runs/justin06lee/issue10-20261011T110443Z-infer/`: `predictions.jsonl`, `inference.json`, `job.json`, `output.log` |
| GX10, CPU outputs | `~/hachi/runs/justin06lee/issue10-20261011T110443Z-cpu/` (`export/`, `score/`). All 206 `score/sha256.json` entries re-verified after copying. |

`score/` holds 12 comparison packets (`write_comparison_packet`: split, both run manifests, configs, origins, evaluations with per-participant metrics, `comparison.json`). It also holds per-comparison decile-loss and calibration files and the identifier-free `aggregate-summary.json` reproduced here. The per-fold comparator `evaluation.json` hashes are listed in the JSON summary for cross-checking against the #9 runner.
