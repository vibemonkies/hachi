# #12: adapted models, ensembles and evidence-backed selection (PMData hourly HR, inner validation)

Aggregate results only. The report contains no participant ids, rows or predictions. The machine-readable summary is [`issue12-pmdata-hourly-selection.json`](issue12-pmdata-hourly-selection.json). Per-participant packets, forecasts and checkpoints stay in approved storage (last section).

**Selected under the predeclared rule: `chronos-2-zero-shot-ctx720`**, i.e. zero-shot Chronos-2 given a 720 h causal heart-rate context.
- **Fine-tuning:** no better than the same model zero-shot (ΔMAE +0.03 bpm).
- **Stacked ensemble:** practically identical to it (ΔMAE −0.01 bpm). Neither cleared the rule's margins.
- **Steps covariate:** made no difference.
- **What helped:** longer context and personal history.

This is inner-validation evidence for **one outer fold**: 12 participants, 1–7 Jan 2020. The selection compares 13 candidates on the same participants, so the selected model's advantage is optimistic. **The outer test (4 participants) stays sealed**; only a separate, parent-owned opening can confirm the result.

## Identity

| | |
|---|---|
| Code | `issue-12-ensemble`. Scoring at `921265f`, export at `7b49924`, both clean trees. |
| Protocol | `configs/evaluation/pmdata-hourly-validation.json`, `document_sha256` `2adbe991…4bd7`, unchanged. Folds, cutoffs and labels are identical to #9/#10. |
| Rule, written before any #12 score | `configs/experiments/pmdata-hourly-selection.json`, `9e1bc4d7…`, first committed in `fc16be6`. The experiment plan is `configs/experiments/pmdata-hourly-adaptation.json` (`5a3078a4…`). Its amendment 1 (`fd704b0`, before any score) adds grouped meta-folds after SnowyFortress's review. Its amendment 2 (`c5b8639`) adds #11's heads as reported comparators only. |
| Dataset | PMData snapshot `06606ac2…ee47` |
| Context policy | `evaluation.context` (#61): 720 h; HR channel is the protocol's feature policy; steps channel is sum, coverage ≥ 0.5, count ≥ 30. Hash `9610dafb…b845`. |
| GPU runtime | GX10 GB10, env `8e30ab7405c3087d` (unchanged; no new env), `amazon/chronos-2@29ec3766…`, weights `ddcda3c7…ba4f42` |
| CPU | Justin's Mac (Darwin arm64), Python 3.12, `uv.lock` |

## How the evidence stays causal

- **Export:** the harness runs with **no labels**. Recording predictors capture every model input over the 3 inner validation manifests and, per amendment 1, 4 grouped meta manifests per inner fold.
- **Meta manifests:** these hold the inner fold's training participants only, over 25–31 Dec 2019. The inner fold's validation participants and the outer test are sealed in every meta manifest, and every meta target ends by the first held-out cutoff.
- **What the GX10 sees:** 612 forecast requests and 2,394 embedding requests, all content-hashed, with no ids or cutoffs. Fine-tune series come from each inner fold's `TrainingPrefix` only.
- **Longer context and the steps covariate:** these come from the bounded `available_by` context helper. At every origin its last 48 h must equal the harness history, or the run fails.
- **Meta-level fitting:** stacking weights and point-model residual intervals are fitted only on meta-fold points. Fine-tuning's best-checkpoint early stopping uses the last 168 h of the training participants' own data.
- **Scoring:** every final candidate is replayed through the harness on **identical origin plans**, which the run checks by hash, and paired with `compare_forecasts`.
- **Cross-checks:**
  - #9's four comparators reproduce exactly (MAE 12.20 / 12.03 / 11.15 / 10.32).
  - Chronos 48 h reproduces #10 exactly (8.94).
  - #11's tree matches #12's tree on all 1,848 points (0 mismatches).

## Candidates

Pooled over the 3 inner folds: 12 participants, 1,599 label-eligible targets. Equal participant weighting; 95% participant bootstrap (1,000 draws, seed 42).
- **Point models** (comparators, ridge heads) carry residual intervals from their own meta-fold out-of-fold errors.
- **Chronos variants and ensembles** carry native q0.1–q0.9.
- **Latency:** one request on the model's serving hardware. Chronos runs on the GX10 GPU; comparators run on Mac CPU in a fresh process.
- **Memory:** that process's peak RSS, plus the CUDA peak for GPU models.
- **#11's heads** (`issue11-*`) are point-only reported comparators without intervals (amendment 2).

| Candidate | Family | MAE | RMSE | 80% coverage | Width | Abstained | p95 latency | Memory |
|---|---|---|---|---|---|---:|---:|---:|
| `train-population-mean-v1` | comparator | 12.20 (10.27 to 14.19) | 16.14 (13.94 to 18.39) | 0.839 (0.761 to 0.911) | 40.33 (39.32 to 41.37) | 0.0% | 0.0 ms | 0.59 GiB |
| `hourly-last-valid-v1` | comparator | 12.03 (10.94 to 13.01) | 17.21 (15.14 to 19.17) | 0.812 (0.773 to 0.846) | 37.19 (36.43 to 38.05) | 0.0% | 0.2 ms | 0.59 GiB |
| `utc-seasonal-naive-v1` | comparator | 11.15 (9.42 to 12.94) | 17.11 (14.56 to 19.73) | 0.745 (0.683 to 0.800) | 30.03 (29.60 to 30.47) | 8.4% | 0.2 ms | 0.60 GiB |
| `causal-hourly-tree-v1` | comparator | 10.32 (9.38 to 11.30) | 14.39 (12.98 to 15.85) | 0.805 (0.764 to 0.842) | 31.27 (30.68 to 31.94) | 7.4% | 3.1 ms | 0.71 GiB |
| `handcrafted-ridge-personal` | ridge | 9.72 (8.87 to 10.60) | 13.93 (12.56 to 15.31) | 0.787 (0.739 to 0.836) | 27.81 (26.90 to 28.80) | 0.0% | 0.3 ms | 0.59 GiB |
| `chronos-2-zero-shot` | chronos | 8.94 (7.69 to 10.17) | 14.01 (11.97 to 15.97) | 0.812 (0.779 to 0.846) | 29.42 (26.48 to 32.65) | 0.0% | 23.4 ms | 1.56 GiB |
| `chronos-2-zero-shot-ctx168` | chronos | 8.39 (7.52 to 9.38) | 13.49 (11.82 to 15.13) | 0.798 (0.775 to 0.819) | 24.54 (22.25 to 26.73) | 0.0% | 23.4 ms | 1.56 GiB |
| `chronos-2-zero-shot-ctx720` | chronos | 8.05 (7.15 to 9.15) | 13.01 (11.47 to 14.56) | 0.782 (0.745 to 0.811) | 23.02 (20.63 to 25.62) | 0.0% | 23.4 ms | 1.56 GiB |
| `chronos-2-zero-shot-steps` | chronos | 8.97 (7.73 to 10.21) | 14.02 (11.95 to 15.92) | 0.830 (0.797 to 0.862) | 30.73 (27.81 to 34.02) | 0.0% | 23.4 ms | 1.56 GiB |
| `chronos-2-embedding-ridge` | ridge | 9.28 (8.23 to 10.48) | 13.69 (11.92 to 15.50) | 0.784 (0.727 to 0.836) | 26.98 (26.02 to 28.01) | 0.0% | 15.1 ms | 1.62 GiB |
| `chronos-2-finetuned` | finetuned | 8.08 (7.08 to 9.22) | 12.98 (11.37 to 14.64) | 0.767 (0.730 to 0.801) | 22.76 (20.59 to 25.07) | 0.0% | 15.4 ms | 2.24 GiB |
| `ensemble-equal-weight` | ensemble | 8.63 (7.66 to 9.76) | 13.22 (11.51 to 14.86) | 0.353 (0.323 to 0.387) | 11.06 (9.95 to 12.23) | 0.0% | 112.3 ms | 1.62 GiB |
| `ensemble-stacked` | ensemble | 8.04 (7.12 to 9.14) | 12.97 (11.40 to 14.57) | 0.792 (0.762 to 0.816) | 22.84 (20.55 to 25.16) | 0.0% | 112.3 ms | 1.62 GiB |
| `handcrafted-ridge-population` | ridge | 11.65 (10.02 to 13.24) | 15.40 (13.67 to 17.21) | 0.811 (0.736 to 0.878) | 35.33 (34.30 to 36.33) | 0.0% | 0.2 ms | 0.59 GiB |
| `issue11-ridge-handcrafted` | external | 9.78 (8.83 to 10.74) | 13.78 (12.21 to 15.35) | — | — | 7.4% | — | — |
| `issue11-ridge-handcrafted-moment` | external | 10.31 (9.43 to 11.17) | 14.17 (12.95 to 15.52) | — | — | 7.4% | — | — |
| `issue11-ridge-handcrafted-wbm` | external | 10.00 (9.09 to 10.83) | 14.19 (12.90 to 15.60) | — | — | 7.4% | — | — |
| `issue11-ridge-moment` | external | 12.64 (11.30 to 13.95) | 16.33 (14.65 to 17.83) | — | — | 7.4% | — | — |
| `issue11-ridge-wbm` | external | 11.57 (10.88 to 12.18) | 15.69 (14.23 to 17.07) | — | — | 7.4% | — | — |


## Selection chain (predeclared incumbent chain)

A challenger replaces the incumbent only if every gate passes:
- paired ΔMAE upper 95% bound < 0;
- paired Δ decile-loss upper bound < 0;
- 80% coverage in [0.75, 0.85];
- abstention ≤ incumbent + 5 pp;
- p95 latency ≤ 1 s;
- memory ≤ 4 GiB.

Each step's comparison packets, one per inner fold, are hash-linked from `selection.steps[].packets` in the JSON.

| Challenger | Incumbent | Paired points | ΔMAE | Δ decile loss | Coverage | Result | Failed gates |
|---|---|---:|---|---|---|---|---|
| `hourly-last-valid-v1` | `train-population-mean-v1` | 1,599 | -0.17 (-1.72 to 1.24) | -0.09 (-0.88 to 0.62) | 0.812 (0.773 to 0.846) | kept incumbent | paired_decile_loss_upper_below, paired_mae_upper_below |
| `utc-seasonal-naive-v1` | `train-population-mean-v1` | 1,464 | -0.95 (-2.66 to 0.80) | -0.47 (-1.33 to 0.47) | 0.745 (0.683 to 0.800) | kept incumbent | abstention_within, coverage_in_range, paired_decile_loss_upper_below, paired_mae_upper_below |
| `causal-hourly-tree-v1` | `train-population-mean-v1` | 1,481 | -1.53 (-2.98 to 0.12) | -0.77 (-1.51 to 0.09) | 0.805 (0.764 to 0.842) | kept incumbent | abstention_within, paired_decile_loss_upper_below, paired_mae_upper_below |
| `handcrafted-ridge-personal` | `train-population-mean-v1` | 1,599 | -2.47 (-4.17 to -0.69) | -1.24 (-2.07 to -0.34) | 0.787 (0.739 to 0.836) | promoted | none |
| `chronos-2-zero-shot` | `handcrafted-ridge-personal` | 1,599 | -0.78 (-2.00 to 0.12) | -1.25 (-1.77 to -0.86) | 0.812 (0.779 to 0.846) | kept incumbent | paired_mae_upper_below |
| `chronos-2-zero-shot-ctx168` | `handcrafted-ridge-personal` | 1,599 | -1.33 (-2.21 to -0.64) | -1.47 (-1.87 to -1.16) | 0.798 (0.775 to 0.819) | promoted | none |
| `chronos-2-zero-shot-ctx720` | `chronos-2-zero-shot-ctx168` | 1,599 | -0.34 (-0.51 to -0.16) | -0.17 (-0.23 to -0.09) | 0.782 (0.745 to 0.811) | promoted | none |
| `chronos-2-zero-shot-steps` | `chronos-2-zero-shot-ctx720` | 1,599 | 0.92 (0.36 to 1.39) | 0.39 (0.17 to 0.58) | 0.830 (0.797 to 0.862) | kept incumbent | paired_decile_loss_upper_below, paired_mae_upper_below |
| `chronos-2-embedding-ridge` | `chronos-2-zero-shot-ctx720` | 1,599 | 1.22 (0.81 to 1.64) | 1.41 (1.19 to 1.63) | 0.784 (0.727 to 0.836) | kept incumbent | paired_decile_loss_upper_below, paired_mae_upper_below |
| `chronos-2-finetuned` | `chronos-2-zero-shot-ctx720` | 1,599 | 0.03 (-0.14 to 0.23) | 0.03 (-0.05 to 0.13) | 0.767 (0.730 to 0.801) | kept incumbent | paired_decile_loss_upper_below, paired_mae_upper_below |
| `ensemble-equal-weight` | `chronos-2-zero-shot-ctx720` | 1,599 | 0.58 (0.35 to 0.81) | 0.51 (0.39 to 0.64) | 0.353 (0.323 to 0.387) | kept incumbent | coverage_in_range, paired_decile_loss_upper_below, paired_mae_upper_below |
| `ensemble-stacked` | `chronos-2-zero-shot-ctx720` | 1,599 | -0.01 (-0.06 to 0.03) | 0.00 (-0.03 to 0.03) | 0.792 (0.762 to 0.816) | kept incumbent | paired_decile_loss_upper_below, paired_mae_upper_below |

**Selected:** `chronos-2-zero-shot-ctx720`

## Ablations (reported; not selection gates)

| Ablation | Base | Challenger | Paired points | ΔMAE | Δ decile loss |
|---|---|---|---:|---|---|
| channel: past steps | `chronos-2-zero-shot` | `chronos-2-zero-shot-steps` | 1,599 | 0.03 (-0.07 to 0.14) | 0.01 (-0.02 to 0.04) |
| context: 168 h | `chronos-2-zero-shot` | `chronos-2-zero-shot-ctx168` | 1,599 | -0.55 (-0.99 to -0.04) | -0.21 (-0.40 to -0.01) |
| context: 720 h | `chronos-2-zero-shot` | `chronos-2-zero-shot-ctx720` | 1,599 | -0.89 (-1.38 to -0.35) | -0.38 (-0.59 to -0.16) |
| representation: Chronos embedding vs handcrafted | `handcrafted-ridge-personal` | `chronos-2-embedding-ridge` | 1,599 | -0.45 (-1.36 to 0.27) | -0.22 (-0.68 to 0.12) |
| personalization: personal history vs population only | `handcrafted-ridge-population` | `handcrafted-ridge-personal` | 1,599 | -1.93 (-2.98 to -0.94) | -0.96 (-1.52 to -0.46) |
| adaptation: fine-tuned vs zero-shot (same context) | `chronos-2-zero-shot-ctx720` | `chronos-2-finetuned` | 1,599 | 0.03 (-0.14 to 0.23) | 0.03 (-0.05 to 0.13) |
| combination: stacked vs equal weight | `ensemble-equal-weight` | `ensemble-stacked` | 1,599 | -0.59 (-0.83 to -0.38) | -0.51 (-0.61 to -0.40) |
| combination: stacked vs Chronos-2 zero-shot | `chronos-2-zero-shot` | `ensemble-stacked` | 1,599 | -0.90 (-1.38 to -0.38) | -0.37 (-0.57 to -0.18) |
| representation: frozen WBM on #11's head | `issue11-ridge-handcrafted` | `issue11-ridge-handcrafted-wbm` | 1,481 | 0.22 (-0.46 to 0.96) | 0.11 (-0.21 to 0.46) |
| representation: frozen MOMENT on #11's head | `issue11-ridge-handcrafted` | `issue11-ridge-handcrafted-moment` | 1,481 | 0.53 (-0.08 to 1.08) | 0.26 (-0.05 to 0.56) |
| representation: #11 handcrafted ridge vs #12 handcrafted ridge | `handcrafted-ridge-personal` | `issue11-ridge-handcrafted` | 1,481 | 0.18 (-0.09 to 0.47) | 0.09 (-0.05 to 0.23) |


## Ensembles

- **Stacking:** per decile, nonnegative weights summing to 1, fitted by linear programme on meta out-of-fold points only. Per fold, 971 / 1,019 / 1,110 complete labelled meta points went into the fit. The median-level weights went almost entirely to the long-context Chronos variants: 720 h 0.53–0.76, 168 h 0.15–0.47, embedding ridge ≤ 0.07. The result is practically indistinguishable from `chronos-2-zero-shot-ctx720` (ΔMAE −0.01, CI −0.06 to 0.03) at five times its latency.
- **Equal weight:** worse (+0.58). Point members averaged into the quantiles collapse the interval: coverage 0.35, which fails the gate.

## Fine-tuning (targeted adaptation)

- **Setup:** full fp32 Chronos-2 fine-tuning in the pinned env (bf16/tf32 off), 720 h context (the predeclared rule: the zero-shot context with the lowest validation MAE), batch 64, AdamW (fused), linear schedule, seed 42.
- **Runs:** up to 1000 steps, eval every 100, best checkpoint kept, one run per inner fold and learning rate. Each run took about 12 min on the GB10, with 5.2 GiB CUDA peak in training.
- **Learning rate:** 1e-6 was chosen on pooled validation MAE (8.08 vs 8.38 for 1e-5).
- **Early stopping:** holdout loss rose after 100–500 steps in every run, so early stopping stopped early everywhere.
- **Result:** the fine-tuned model is no better than the zero-shot model with the same context (ΔMAE +0.03, CI −0.14 to 0.23). Its 80% coverage is 0.767.
- **Provenance:** checkpoints and full receipts (optimizer, seed, steps, loss history, weight hashes) are on the GX10.
- **Negative result:** with 8 training participants and about 7 weeks of hourly data per fold, adaptation does not help.

## Selected artifact: reloaded and verified

- **Pin:** `chronos-2-zero-shot-ctx720-5ed7c6cb5c72c423@6711a8f625ef7f53010a00b2c21b914f04cdc765f8b33183996df70cf7bebf24`. It's a `ChronosArtifact` in the baselines' `Receipt` format holding the checkpoint pin, runtime lock, adapter settings and the 720 h context policy. There are no weights: zero-shot.
- **Reload:** loaded by receipt with source hashes checked. Every inner-validation request was rebuilt from the artifact alone: 77 requests, ids identical to the scored run. All three folds' evaluations hash-equal the scored packets (`d20646aa…`, `4d73ffc2…`, `dd84acd8…`).
- **Fresh GX10 runs:**
  - Re-running the full 612-request file in a new process gives **byte-identical** forecasts (`5574b932…`).
  - Running only the artifact's 77 requests (a different batch composition) agrees to within **0.00015 bpm**. The difference is float32 kernel batching, not model state.
- **Served packet:** `run.json` names the artifact, for #16's loader. **Calibration:** none after selection; the q0.1–q0.9 interval is served as `uncalibrated`.

## Negative results and limitations

- **No adaptation or combination gain.** Fine-tuning, the stacked ensemble, the steps covariate and the Chronos-embedding ridge head all failed to beat zero-shot long-context Chronos-2. #11's frozen WBM and MOMENT add nothing over handcrafted features on #11's head.
- **Selection optimism.** Thirteen candidates were compared on the same 12 participants and 7 days. The rule's confidence bounds are per comparison, not family-wise. Treat the selected model's validation numbers as optimistic until the sealed outer test is opened.
- **Rule written after #9/#10.** The selection rule was written after the #9 and #10 results were public, which is disclosed in the rule. Amendment 2 adds #11's heads, whose scores were already public, so they are reported comparators, not candidates.
- **Small and short.** 12 participants and one week; the intervals are wide.
- **Calibration scope.** Coverage was measured on the same validation targets. The 720 h model's 80% coverage, 0.782 (0.745 to 0.811), sits near the gate's lower edge. Served intervals are labelled `uncalibrated`.
- **Latency sampling.** Chronos latency comes from single-request samples on the GX10 that mix context lengths. The 720 h model is the heaviest of them, but all stay far under the 1 s budget.
- **Dataset assumptions.** PMData clock mapping and historical availability remain documented assumptions (#5). PMData has no illness labels, so nothing here concerns illness discrimination.

## Approved storage

| Copy | Location |
|---|---|
| Justin's T7 | `/Volumes/T7/Stockpile/hachi.datasets/runs/justin06lee/issue12-20261011T115932Z/` (`export/`, `gx10-*`, `score/` + `score-sha256.json` index `db8015a4…`, `artifact-verification.json`) |
| GX10 runs | `~/hachi/runs/justin06lee/issue12-20261011T115932Z-{zeroshot,embed,ft-<fold>-<lr>,reproduce,rerun-zeroshot,cpu}/`. Fine-tuned checkpoints are under `…-ft-*/trainer/`. |
| Selected artifact | GX10 `~/hachi/artifacts/chronos-2-zero-shot-ctx720-5ed7c6cb5c72c423/` (read-only); T7 `hachi.datasets/artifacts/justin06lee/issue12-selected-issue12-20261011T115932Z/` |

Commands are in [`src/hachi/models/training/README.md`](../../src/hachi/models/training/README.md).
