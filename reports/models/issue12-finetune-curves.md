# #12 Chronos-2 fine-tune training curves (aggregate)

These are the training logs of the six #12 fine-tunes, as aggregate scalars only. The full curves are in [`issue12-finetune-curves.json`](issue12-finetune-curves.json): train loss, learning rate and grad norm, plus eval loss, all every 100 steps, with hyperparameters, timing, memory and hashes. The file holds no inputs, participant ids, predictions or weights. The selection context is in [`issue12-pmdata-hourly-selection.md`](issue12-pmdata-hourly-selection.md).

**Setup, identical for every run:**
- full fp32 fine-tuning of `amazon/chronos-2@29ec3766…` in the pinned GX10 env;
- 720 h context, 24 h horizon, batch 64, up to 1000 steps;
- AdamW (fused), linear decay, no warmup, seed 42;
- eval every 100 steps on a temporal holdout: the last 168 h of the inner fold's 8 training participants before 2020-01-01;
- the best checkpoint by eval loss is kept.

Losses are Chronos-2's quantile training loss, so they are not bpm.

| Inner fold | LR | Best step | Best eval loss | Eval loss, step 100 → 1000 | Train loss, step 100 → 1000 | Wall time | Peak CUDA (train) |
|---|---|---:|---:|---|---|---:|---:|
| 0 | 1e-06 | 300 | 4.229 | 4.260 → 4.262 | 3.770 → 3.387 | 12.0 min | 5.19 GiB |
| 0 | 1e-05 | 100 | 4.287 | 4.287 → 4.996 | 3.507 → 2.110 | 12.4 min | 5.19 GiB |
| 1 | 1e-06 | 100 | 4.070 | 4.070 → 4.157 | 3.937 → 3.637 | 12.3 min | 5.19 GiB |
| 1 | 1e-05 | 100 | 4.039 | 4.039 → 5.078 | 3.735 → 2.264 | 12.0 min | 5.19 GiB |
| 2 | 1e-06 | 500 | 4.085 | 4.156 → 4.116 | 3.864 → 3.528 | 12.3 min | 5.19 GiB |
| 2 | 1e-05 | 100 | 4.171 | 4.171 → 4.743 | 3.605 → 2.235 | 12.3 min | 5.19 GiB |

**Eval loss every 100 steps (100 … 1000):**
- inner 0, lr 1e-06: 4.260 4.256 4.229 4.238 4.237 4.237 4.268 4.265 4.259 4.262
- inner 0, lr 1e-05: 4.287 4.499 4.654 4.821 4.818 4.927 4.914 4.999 4.998 4.996
- inner 1, lr 1e-06: 4.070 4.086 4.071 4.080 4.120 4.135 4.139 4.152 4.155 4.157
- inner 1, lr 1e-05: 4.039 4.338 4.619 4.738 4.888 5.005 4.929 5.124 5.112 5.078
- inner 2, lr 1e-06: 4.156 4.112 4.096 4.093 4.085 4.090 4.098 4.113 4.119 4.116
- inner 2, lr 1e-05: 4.171 4.249 4.463 4.516 4.577 4.664 4.701 4.759 4.759 4.743

## Reading

- **1e-5 overfits within about 100 steps.** Train loss keeps falling (to ≈2.1–2.3) while holdout loss rises from ≈4.0–4.3 to ≈4.7–5.1. Early stopping kept step 100 in every 1e-5 run.
- **1e-6 barely moves the model.** Holdout loss is nearly flat (best at step 100–500), and train loss falls slowly.
- **Learning-rate choice:** on the inner-validation folds, 1e-6 was chosen by the predeclared rule (pooled MAE 8.08 vs 8.38 bpm).
- **Net effect:** the chosen model is no better than the same Chronos-2 zero-shot: ΔMAE +0.03 bpm (-0.14 to +0.23).

**Limitation:** no step-0 eval was logged, so the holdout loss of the unadapted model isn't in these curves. The zero-shot comparison comes from the inner-validation scoring instead. Each fold trains on 8 participants with roughly 7 weeks of hourly data, which is little data for a 120M-parameter forecaster.
