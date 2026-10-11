# Apple-like heart-rate density: how much do the served forecasters degrade? (PMData validation folds)

This report has aggregate results only: no participant ids, rows, cutoffs or predictions. The machine-readable summary is [`apple-density-pmdata-hourly-validation.json`](apple-density-pmdata-hourly-validation.json).

**Why.** PR #85 found that typical 5-minute Apple Watch heart rate abstains at the served models' density gates. The frozen protocol was set on PMData's Fitbit data, with a median of 433 native samples per hour against a gate of ≥ 30. An Apple Watch at rest records about 12 per hour.

**The question.** Same models, splits, cutoffs and full-density targets: how much worse is the forecast of *true* hourly HR when the models' history is thinned to an Apple-like cadence?

**What it is not.** It is not evidence about real Apple Watch data. Device, wear-pattern and sampling-irregularity shifts remain (see Limitations). It is not a held-out test result: the outer test stays sealed. It is not a selection either; it is a candidate input to #12.

## Amendment 1: Apple-helper coverage (supersedes the original gate wording)

BoldHorizon (`hachi-issue-16`) found that the original variant's coverage didn't match served Apple features.
- **Original variant:** coverage = share of 5-minute slots holding a sample, so full 5-minute cadence gives 12/12 = 1.0.
- **Served Apple features** (`hachi.data.apple_health.hourly`, rule `apple-hour-end-sealed-native-v1`): coverage = distinct sampled start minutes / 60, so the same cadence gives 12/60 = 0.2.
- **Consequence:** a gate of "coverage ≥ 0.5" validated here would still abstain on every typical Apple hour.

**The amendment:** [`configs/evaluation/pmdata-hourly-validation-apple-minute-density.json`](../../configs/evaluation/pmdata-hourly-validation-apple-minute-density.json), file sha256 `72c75819…ffee`, protocol `document_sha256` `3629a9b8d98404edf187584375341e2f98351b363fc06a306895e5d229ab23f3`. It pins the original variant by SHA-256 and was committed at `8ce2530`. Timing: after the original variant was scored, but before its own scoring.
- **Coverage** is computed exactly as the Apple helper does: distinct sampled start minutes / 60. A bin is null only when it holds no sample.
- **The gate is coverage ≥ 0.10 and ≥ 6 samples per hour,** the frozen coverage-0.5 rule at 5-minute cadence in that denominator. The audit under this definition supports it:
  - all 46,406 frozen-admitted hours keep coverage ≥ 0.10 (min 0.10, p01 0.133, median 0.20);
  - coverage ≥ 0.15 would drop 1.1% of them with no structural basis.
- **No gate is chosen from scores.** Under thinning, each kept sample sits in its own minute, so minute coverage ≥ 0.10 holds exactly when the original slot rule did. The admitted hours are identical (46,674). Rerun at `21a78e4`, all 15 thinned-history evaluations (5 models × 3 folds) have **identical predictions and counts**. The thinned Chronos request file is byte-identical (`3a2bcb87…`), and so is the paired-points file. **Every number below holds unchanged for the amended gate.**
- **Scope:** this is evidence about **cadence** only. It is not a validation of a real Apple device, wear pattern or physiology.
- **Serving:** a served Apple model is a **new artifact**, staged and evaluated at these gates. It never overrides the original receipt, and WindyTrout's PR #91 enforces that.

## Answer

**At the density-matched gate, Apple-like history costs nothing measurable.**

| Model | ΔMAE thin − full (bpm, 95% CI) |
|---|---|
| Chronos-2 zero-shot | +0.01 (−0.11 to +0.13) |
| last-valid | +0.06 (−0.25 to +0.34) |
| train population mean | −0.06 (−0.19 to +0.09) |
| causal tree | −0.14 (−0.30 to 0.00) |
| seasonal-naive | −0.21 (−0.32 to −0.09) |

- **Every interval includes or sits below zero.** No model loses a meaningful amount.
- **Coverage.** The origin plans are identical. The thinned gate admits slightly more hours, so the tree and seasonal-naive abstain *less*.
- **Chronos's 80% interval** covers 0.83 on thinned history vs 0.81 on full.

What an admission can cite: on PMData, hourly HR means with **≥ 6 samples and Apple-helper coverage ≥ 0.10** (distinct sampled minutes / 60; ≥ 6 distinct 5-minute slots at this cadence) forecast true hourly HR as well as full-density means, for all five served models. This is cadence evidence only.

## The original variant (predeclared, committed before any score)

- **File:** [`configs/evaluation/pmdata-hourly-validation-apple-density.json`](../../configs/evaluation/pmdata-hourly-validation-apple-density.json), committed at `132a219` before scoring. File sha256 `a5bd17c2…aa43`; protocol `document_sha256` `4aad3a87fa7fd390304031bd5e49b31ed2affe23edcfe6a6a9ea987323f7ee27`.
- **Base:** the frozen protocol `configs/evaluation/pmdata-hourly-validation.json` (`2adbe991…4bd7`), pinned by file SHA-256. `load_variant` refuses any difference except the model-input density gates.
- **Thinning** (fixed phase, no randomness): within each UTC-aligned 5-minute slot, keep the sample with the earliest start, ties broken by `record_id`. Hourly bins are rebuilt with the pipeline's own rules, from `hachi.data.pmdata.aggregates`:
  - every original bin is kept;
  - the value is the mean of kept samples;
  - `observed_count` is the number of kept samples;
  - coverage is the share of the hour's 12 slots holding a sample;
  - a bin below the pipeline's 0.5 hourly coverage is null;
  - availability is the latest kept sample's, never before the bin ends.

  20,985,494 samples become 556,943 kept samples.
- **Only change:** `feature_policy.min_observed_count` and every comparator's `min_samples_per_hour`, both from 30 to **6**. Coverage stays ≥ 0.5. **Targets keep their full-density gates** (coverage ≥ 0.5, count ≥ 30 on the original labels).
- **Why 6 (pre-scoring audit, not scores):** 30 covered minutes always span ≥ 6 five-minute slots, so "≥ 6 of 12 slots" is the frozen coverage-0.5 rule at the thinned cadence.
  - All 46,406 hours the frozen protocol admits keep ≥ 6 thinned samples: min 6, p01 8, median 12.
  - The gate newly admits 268 hours (0.6%).
  - The frozen gate of ≥ 30 rejects every thinned hour, since none holds more than 12.

### The gate in each source's own denominator

| | Rule |
|---|---|
| Validated here | ≥ 6 kept samples in the hour, at most one per UTC 5-minute slot, so ≥ 6 of 12 slots observed (slot coverage ≥ 0.5) |
| The same rule as sampled-minute density | ≥ 6 of 60 minutes sampled (minute-density coverage ≥ 0.1), each in a distinct 5-minute slot |
| Frozen protocol | native count ≥ 30 and minute coverage ≥ 0.5 |

A source that reports Apple HR coverage as sampled-minute density gets 12/60 = 0.2 at 5-minute cadence, so it would still abstain under "coverage ≥ 0.5". This evidence supports the validated rule stated in that source's own denominator. It does not license relabelling one coverage as the other. Turning it into an `--admit-apple` policy is a separate frozen decision (BoldHorizon, `hachi-issue-16`).

## Identity and cross-checks

| | |
|---|---|
| Code | `apple-density-validation`. Export at `fbcb75c`; scoring at `748aaa3`, which only fixes a field name in the output writer. Both trees clean. |
| Dataset | PMData `simula-2020-04-24`, snapshot `06606ac2…ee47` |
| Splits | Nested plan `df6fd2b3…1c06`; inner validation splits `13a312b2…`, `4b63051a…`, `f385983f…`, identical to the frozen protocol's. Outer fold 0 test sealed. |
| Chronos-2 | `amazon/chronos-2@29ec3766…`, GX10 env `8e30ab7405c3087d` (unchanged), via `scripts/gx10/gpu-run --owner justin06lee`. Jobs `apple-density-20261011T130430Z-full` and `-thin`, both exit 0. Context 48 h, the protocol lookback. Bindings: `configs/models/chronos/pmdata-hourly-hr.json` (full) and `pmdata-hourly-hr-apple-density.json` (thin, bound to `4aad3a87…`). |
| Requests | Full `bacf077b…` (**identical to #10's request file**); thin `3a2bcb87…`. 77 contexts each, on the same origins. |
| Full-density reproduction | All 12 full-density comparator `evaluation.json` hashes match SnowyFortress's published [`packet-index.json`](../evaluation/pmdata-hourly-validation/packet-index.json) **byte for byte**. |

## Results

There are 12 validation participants, 84 planned origins and 2,016 target hours.
- 7 origins (168 hours) lack history under both densities.
- 249 target hours have no eligible full-density label.

Pairing is per participant, cutoff and target hour, on targets both histories predicted. Equal participant weight; participant bootstrap, 1,000 resamples, seed 42. Units are bpm.

### Paired accuracy (same targets)

| Model | Paired targets | MAE full | MAE thin | ΔMAE | ΔRMSE | Participants worse / better | Per-fold ΔMAE |
|---|---:|---|---|---|---|---|---|
| Chronos-2 zero-shot | 1,599 | 8.94 (7.69 to 10.17) | 8.94 (7.75 to 10.12) | +0.01 (−0.11 to 0.13) | +0.03 (−0.11 to 0.17) | 6 / 6 | −0.11, +0.12, +0.01 |
| last-valid | 1,599 | 12.03 (10.94 to 13.01) | 12.09 (10.97 to 13.15) | +0.06 (−0.25 to 0.34) | +0.09 (−0.18 to 0.38) | 6 / 6 | −0.05, +0.29, −0.06 |
| train population mean | 1,599 | 12.20 (10.27 to 14.19) | 12.13 (10.26 to 14.17) | −0.06 (−0.19 to 0.09) | 0.00 (−0.11 to 0.12) | 6 / 6 | +0.03, −0.16, −0.06 |
| causal tree | 1,481 | 10.32 (9.38 to 11.30) | 10.18 (9.33 to 11.13) | −0.14 (−0.30 to 0.00) | −0.05 (−0.18 to 0.09) | 4 / 8 | +0.03, −0.19, −0.27 |
| seasonal-naive | 1,464 | 11.15 (9.42 to 12.94) | 10.94 (9.31 to 12.64) | −0.21 (−0.32 to −0.09) | −0.56 (−0.84 to −0.29) | 2 / 10 | −0.37, 0.00, −0.27 |

Chronos-2's 80% interval coverage on the paired targets is 0.81 (0.78 to 0.85) on full history and 0.83 (0.79 to 0.86) on thinned (Δ +0.01, 0.00 to +0.03).

### Coverage

| Model | Scored, full | Scored, thin | Abstained, full | Abstained, thin | Thin-only targets |
|---|---:|---:|---:|---:|---:|
| Chronos-2 zero-shot | 1,599 | 1,599 | 0 | 0 | 0 |
| last-valid | 1,599 | 1,599 | 0 | 0 | 0 |
| train population mean | 1,599 | 1,599 | 0 | 0 | 0 |
| causal tree | 1,481 | 1,499 | 118 | 100 | 18 |
| seasonal-naive | 1,464 | 1,473 | 135 | 126 | 9 |

No target that full-density history predicted was lost with thinned history.

**Why thinning can even help slightly.** The tree and seasonal-naive rely on the latest completed hours. The thinned gate admits a few hours that the frozen 30-sample gate rejected (where minute coverage fell below 0.5 but samples still spanned 6+ slots), so those models abstain less. The small seasonal-naive gain probably reflects a 12-sample mean damping short bursts in the history hour. It is not a claim that sparser data is better.

## Limitations

- **Not Apple data.** This is Fitbit data thinned on a fixed UTC grid. Real Apple Watch sampling is irregular (often 4–7 min apart, denser during workouts, sparser with poor fit). Its wear pattern and sensor also differ. 96% of thinned admitted hours hold all 12 slots, because PMData wear is near-continuous; real Apple hours may sit nearer the gate more often. A sparser-cadence sensitivity (e.g. 10-minute) was not run. It would need its own predeclared variant.
- **Device shift remains.** Fitbit and Apple heart-rate algorithms differ, and nothing here measures that.
- **Targets are full density** by design. Scoring against Apple-derived targets would be a different question.
- **Small sample:** 12 participants over one week, validation folds only. The outer test is sealed.

## Approved storage

Participant-level data never goes to Git or GitHub.
- **Private outputs:** exports, GX10 runs, per-fold evaluations and `paired-points.parquet` are on Justin's T7 at `hachi.datasets/runs/justin06lee/apple-density-20261011T130430Z/`, mirrored on the GX10 at `~/hachi/runs/justin06lee/apple-density-20261011T130430Z/`.
- **Amendment 1 rerun:** `…/apple-minute-density-20261011T135904Z/` (T7 and GX10). `score/summary.json` sha256 `f5144fc4…ac2f`; `paired-points.parquet` `d79f55a0…45ed`, identical to the original.
- **Hashes:** `score/summary.json` sha256 `759e5fbc…8e2e`; `paired-points.parquet` `d79f55a0…45ed`.
