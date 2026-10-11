# CMU challenge-cohort recovery comparison

Research evidence only. Production recovery prediction abstains; no recovery date is displayed.

## Provenance and fixed protocol

Clean source: `bb70d19afcef3b10af0e3ba9467b4c52da927090` (`git_dirty=false`). Both protocols were committed before corrected scores in `af09ba3`; subsequent commits handle no-information truncation and integrate main without changing model choices.

Snapshot: `7c1429b102ebf5bcb5c0f94db0aba6c1e290d1b0b78aeae68c7105b3cfda38c3`.
Combined config: `da6673c84e000a4bbdde62c5f9cd0b5ab92b6808a9e3b01a58eb612af6a1c4bd`.
Split protocol: `0f9b7b6f49ce382574ee3b1692ecbe4b9ce712991d1cd0ebef1376938d2e03bb`.
Fold plan: `f95b01edbd73c7511e517b03a1bf9e4a887d19f416b2a172b523b4eb2d790016`.
Lock: `1b290745f51cf459018c95226823b49db1422e08817402bfc111fef0c30b1297`; Python `3.12.13`.
Byte-identical runner receipt: [cmu.json](cmu.json), SHA256 `80b95fe9b2cccca51701506e18fc7a903df6bca97d33c50102e089c841f9b35d`.

Private packet: `/Users/ezzyrappeport/hachi/runs/NavyOwl/recovery-cmu-relative-04`. Private weights, assignments and participant predictions stay local. All 32 files and 7 directories have no group/other permission bits.

```sh
/Users/ezzyrappeport/hachi/runtime/navyowl/venv/bin/python -I -m hachi.models.recovery \
  --snapshot /Users/ezzyrappeport/hachi/data/derived/clinical-labels-2-cmu-common-cold-project-retrieved-2026-10-10-7c1429b102eb \
  --config configs/experiments/recovery/cmu.json \
  --output /Users/ezzyrappeport/hachi/runs/NavyOwl/recovery-cmu-relative-04
```

The command ran in the isolated recovery worktree. Reproduction needs a new private output directory and the recorded clean source.

The endpoint is `outcomes-1-sustained-symptom-free-2d`: first day of an observed two-day symptom-free run, retrospectively confirmed only at the end of the second day. Retain resolved intervals (`S(L-1)-S(U)`); censor through the last observed symptomatic or intermediate day (`S(C)`), including conservatively across gaps. Exclude zero remaining follow-up. One first-observed-symptomatic end-of-day landmark per episode uses only the current source-native symptom score. Retrospective onset/category/test/resolution are not predictors. Eligibility still requires retrospective episode ascertainment and future follow-up.

Whole-person outer4/inner3/mintrain4/seed42 folds are assigned using identity-only full-roster projection before task filtering; only outer0 development participants have outcome/predictor reads. No test scoring, selection, refit or post-score calibration.

Constant daily training-cohort hazard versus ridge logistic hazard with intercept, log future day and static current symptoms; ridge0.1, maximum3000 iterations, tolerance1e-6, cluster bootstrap1000. This comparison does not isolate the added symptom contribution from time-shape differences.

Clock: `relative_to_challenge` (study day N = 2000-01-01 + N); no calendar alignment. Predictor: native `jackson_adjusted`, the baseline-adjusted eight-item Jackson total, available only at end of its study day. No app-severity conversion, wearable/date/serology/shedding joins or 7/14-day transfer.

The frozen primary horizon is2d, calibration1/2/3d, exports<=3d. Quarantine follow-up is5d (6d for influenza); each export day needs at least20 distinct training people known at risk and each fold at least20 training resolutions. Known at risk means C>=day for censoring or L>day for a resolved interval. These pre-score conservative research thresholds do not establish clinical accuracy or generalize beyond this challenge cohort.

## Development support and held-out comparison

All counts below are generated within the committed runner on development partitions. Disjoint validation audits are summed once, never a full-roster eligibility audit.

Development: 518 canonical episodes; 122 eligible resolved and 367 eligible censored. Excluded: 13 no-follow-up, 16 zero future follow-up, 0 no observed symptomatic landmark. The known-unresolved bound precedes the final survey in 99 development episodes. Actual landmark wearable-day coverage: 0; no wearable predictors.

At 2d, 489 inner-validation episodes from 489 people: baseline censored NLL 0.657445; conditional 0.633204; paired conditional-minus-baseline -0.024242, participant-cluster percentile95% interval [-0.036830, -0.012342]. Lower is better. Bootstrap conditions on fitted models and this active split; it omits training/selection uncertainty. Small-fold intervals are descriptive.

| Inner fold | Train people | Train resolved episodes | Validation people / episodes | Export support days | Baseline NLL | Conditional NLL | Difference95% interval |
|---|---:|---:|---:|---:|---:|---:|---|
| 0 | 322 | 81 | 167 / 167 | 3 | 0.661158 | 0.636046 | [-0.046353, -0.005634] |
| 1 | 330 | 91 | 159 / 159 | 3 | 0.539787 | 0.528022 | [-0.033231, 0.009950] |
| 2 | 326 | 72 | 163 / 163 | 3 | 0.768412 | 0.732891 | [-0.054835, -0.016522] |

Training known-at-risk counts and resolved-event counts by every export day are in the receipt. Both optimizers converged in all folds. Horizon-straddling intervals supply only known pre-interval survival; day1-starting intervals crossing the horizon contribute no score information. This coarsening assumes non-informative observation, not established by these data.

## Calibration and uncertainty

Probabilities are unmodified. Unknown horizon outcomes retain interval identification bounds; none become negative labels. The receipt contains Brier identification bounds and bootstrap intervals for predicted means and both observed bounds.

| Fold | Day | Known / ambiguous | Baseline mean | Conditional mean (95% interval) | Observed resolution fraction bounds | Observed lower / upper bound95% intervals | Conditional Brier bounds |
|---|---:|---:|---:|---|---|---|---|
| 0 | 1 | 167 / 0 | 0.098301 | 0.113055 [0.109182, 0.116951] | [0.143713, 0.143713] | [0.095808, 0.197605] / [0.095808, 0.197605] | [0.119611, 0.119611] |
| 0 | 2 | 153 / 14 | 0.186939 | 0.193441 [0.187000, 0.199939] | [0.215569, 0.299401] | [0.149701, 0.281437] / [0.233533, 0.371257] | [0.164323, 0.214638] |
| 0 | 3 | 135 / 32 | 0.266864 | 0.257412 [0.249046, 0.265878] | [0.239521, 0.431138] | [0.167665, 0.305389] / [0.353293, 0.508982] | [0.175662, 0.263481] |
| 1 | 1 | 159 / 0 | 0.108205 | 0.132302 [0.126589, 0.137633] | [0.106918, 0.106918] | [0.062893, 0.157233] / [0.062893, 0.157233] | [0.094043, 0.094043] |
| 1 | 2 | 147 / 12 | 0.204702 | 0.221906 [0.212599, 0.230618] | [0.157233, 0.232704] | [0.100629, 0.213836] / [0.169811, 0.301887] | [0.133697, 0.174792] |
| 1 | 3 | 119 / 40 | 0.290757 | 0.290976 [0.278908, 0.302132] | [0.194969, 0.446541] | [0.132075, 0.257862] / [0.364780, 0.522013] | [0.163626, 0.270947] |
| 2 | 1 | 163 / 0 | 0.085207 | 0.102611 [0.100114, 0.105193] | [0.190184, 0.190184] | [0.134969, 0.251534] / [0.134969, 0.251534] | [0.159825, 0.159825] |
| 2 | 2 | 155 / 8 | 0.163155 | 0.178396 [0.174193, 0.182758] | [0.257669, 0.306748] | [0.196319, 0.325153] / [0.245399, 0.374233] | [0.192755, 0.224443] |
| 2 | 3 | 132 / 31 | 0.234460 | 0.240150 [0.234685, 0.245862] | [0.306748, 0.496933] | [0.239264, 0.374233] / [0.423313, 0.576687] | [0.209569, 0.308205] |

The conditional model improves pooled two-day log loss within this challenge cohort, but calibration is inadequate for serving: folds0 and2 underpredict observed resolution at the primary horizon, and identification intervals widen at day3. No recalibration was fit after viewing scores. A positive research comparison is not evidence of app-level clinical accuracy or a long-horizon recovery forecast.

## Exports and remaining gates

489 conditional relative-day curves exported and reloaded with exact parity. Unreached quantiles are null: q0.25 156, median 489, q0.75 489. All outputs remain within per-fold supported follow-up; no exact recovery dates or extrapolated quantiles. Research artifact format2 pins native cohort/scale/features/clock and implementation hashes. Every production `predict` call returns `None`.

The private export audit is generated by the runner and independently matches the saved curve count. Published JSON is byte-identical to its private aggregate; no participant rows, identifiers, predictions or weights are published.

Required clinical/application gates remain: an independently accepted endpoint/split/privacy correction; prospectively ascertained recovery follow-up and calibrated inference on a relevant target population; validated app-native symptoms/artifact integration. Unsupported serving remains unavailable, and #14 is not marked delivered by this research packet.
