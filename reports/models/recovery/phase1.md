# Corrected Stanford recovery comparison

Research evidence only. Production recovery prediction abstains; no recovery date is displayed.

## Provenance and fixed protocol

Clean source: `ff561b7bbfe94411f71568f69c1ef4b0ff3e087d` (`git_dirty=false`). The scientific choices and splits were committed before corrected CMU scores in `af09ba3`. Subsequent changes correct censoring/publication metadata and integrate main. CMU protocol version2 changes version/exposure metadata only; every other config field and both split protocols remain unchanged. No post-score tuning, refit or recalibration.

Snapshot: `6a864b03b2d3ddf05abc42b699679dba39f1909bad2c3053c4b8adf4108faf09`.
Combined config: `963555849e40dd594b57e488343636963f3bd576ab9f5c7ea69ea9d7aa2e5e95`.
Split protocol: `60a4345a6feb8f4a192e6aec718e4b364d2f22a93ad8d227e1645d092ec6e82c`.
Fold plan: `13dd73b4b3f2b6beabe105c5e577e86e935fa68edfdc117d8e9ebdc7c772fa5e`.
Lock: `1b290745f51cf459018c95226823b49db1422e08817402bfc111fef0c30b1297`; Python `3.12.13`.
Byte-identical runner receipt: [phase1.json](phase1.json), SHA256 `8349f596afc22a0747393da6df633097a2c53f8e1ebabdc34c78fee911508568`.

Private packet: `/Users/ezzyrappeport/hachi/runs/NavyOwl/recovery-stanford-minimized-01`. Private weights, assignments and participant predictions stay local. All 33 files and 7 directories have no group/other permission bits.

```sh
/Users/ezzyrappeport/hachi/runtime/navyowl/venv/bin/python -I -m hachi.models.recovery \
  --snapshot /Users/ezzyrappeport/hachi/data/derived/clinical-labels-2-stanford-covid19-wearables-2020-nbe-6a864b03b2d3 \
  --config configs/experiments/recovery/phase1.json \
  --output /Users/ezzyrappeport/hachi/runs/NavyOwl/recovery-stanford-minimized-01
```

The command ran in the isolated recovery worktree. Reproduction needs a new private output directory and the recorded clean source.

The endpoint is `outcomes-1-sustained-symptom-free-2d`: first day of an observed two-day symptom-free run, retrospectively confirmed only at the end of the second day. Retain resolved intervals (`S(L-1)-S(U)`); censor through the last observed symptomatic or intermediate day (`S(C)`), including conservatively across gaps. Exclude zero remaining follow-up. One first-observed-symptomatic end-of-day landmark per episode uses only the current source-native symptom score. Retrospective onset/category/test/resolution are not predictors. Eligibility still requires retrospective episode ascertainment and future follow-up.

Whole-person outer4/inner3/mintrain4/seed42 folds are assigned using identity-only full-roster projection before task filtering; only outer0 development participants have outcome/predictor reads. No test scoring, selection, refit or post-score calibration.

Constant daily training-cohort hazard versus ridge logistic hazard with intercept, log future day and static current symptoms; ridge0.1, maximum3000 iterations, tolerance1e-6, cluster bootstrap1000. This comparison does not isolate the added symptom contribution from time-shape differences.

**Supersedes the invalid af7e26b/PR67 packet.** The prior exploratory eligibility audit loaded whole-roster surveys/recovery labels outside the runner and its published counts exposed test aggregates by subtraction. Those counts and numerical claims are withdrawn, including from this worker's prior PR/issue status text. Historical Stanford blinding is compromised; removing text cannot restore it. Current runs read development outcomes only, retain the same split and model choices, and explicitly record historical exposure without repeating test aggregates.

Clock: `floating_local_shifted`, represented with Z; **not actual UTC**. Predictors: symptom count, maximum severity and severity sum on the Stanford daily severity scale. Primary7d/calibration3,7,14/export<=14d, original minimum5 training people with label extent and minimum1 training resolution retained. This permissive event gate and label-extent support are limitations, not clinical adequacy.

## Development support and held-out comparison

**Aggregate disclosure (B3).** Previously published development audits repeated #8 endpoint categories. Combined with the existing source-wide #8 audits, those counts made test-partition outcome totals derivable. Both cohort receipts now record historical aggregate exposure. Removing category breakdowns cannot restore past blindness. Task eligibility correlates with source categories, so test-partition label totals remain roughly inferable from #8's whole-cohort audit; where eligibility coincides, some categories may be exactly inferable. No test-total subtraction is performed or published. No new test-outcome read/scoring is authorized, and no blind-final-test claim is made. Parent retains any decision about the compromised partition.

Publication receipt format3 allowlists #14 task eligibility and task-specific exclusions on development partitions, including per-fold audits. Full source-category counts remain only in runner-owned private `private-audit.json`. Disjoint validation task audits are summed once; no full-roster task eligibility audit is performed.

Development task support: 4 eligible resolved and 13 eligible censored episodes. Task-specific exclusions include 2 zero remaining future follow-up and 6 no observed symptomatic landmark. The known-unresolved bound precedes the final survey in 1 development episodes. Actual landmark wearable-day coverage: 14; no wearable predictors.

At 7d, 17 inner-validation episodes from 16 people: baseline censored NLL 0.375031; conditional 0.375245; paired conditional-minus-baseline 0.000213, participant-cluster percentile95% interval [-0.058136, 0.041211]. Lower is better. Bootstrap conditions on fitted models and this active split; it omits training/selection uncertainty. Small-fold intervals are descriptive.

| Inner fold | Train people | Train resolved episodes | Validation people / episodes | Export support days | Baseline NLL | Conditional NLL | Difference95% interval |
|---|---:|---:|---:|---:|---:|---:|---|
| 0 | 11 | 1 | 5 / 5 | 14 | 1.142595 | 1.066954 | [-0.228909, 0.004746] |
| 1 | 10 | 3 | 6 / 7 | 14 | 0.039075 | 0.101600 | [0.028594, 0.099983] |
| 2 | 11 | 4 | 5 / 5 | 14 | 0.077808 | 0.066637 | [-0.014632, -0.008277] |

Training known-at-risk counts and resolved-event counts by every export day are in the receipt. Both optimizers converged in all folds. Horizon-straddling intervals supply only known pre-interval survival; day1-starting intervals crossing the horizon contribute no score information. This coarsening assumes non-informative observation, not established by these data.

## Calibration and uncertainty

Probabilities are unmodified. Unknown horizon outcomes retain interval identification bounds; none become negative labels. The receipt contains Brier identification bounds and bootstrap intervals for predicted means and both observed bounds.

| Fold | Day | Known / ambiguous | Baseline mean | Conditional mean (95% interval) | Observed resolution fraction bounds | Observed lower / upper bound95% intervals | Conditional Brier bounds |
|---|---:|---:|---:|---|---|---|---|
| 0 | 3 | 5 / 0 | 0.005245 | 0.005356 [0.003203, 0.007601] | [0.000000, 0.000000] | [0.000000, 0.000000] / [0.000000, 0.000000] | [0.000035, 0.000035] |
| 0 | 7 | 5 / 0 | 0.012195 | 0.013256 [0.007932, 0.018790] | [0.200000, 0.200000] | [0.000000, 0.600000] / [0.000000, 0.600000] | [0.193518, 0.193518] |
| 0 | 14 | 5 / 0 | 0.024241 | 0.027888 [0.016701, 0.039439] | [0.400000, 0.400000] | [0.000000, 0.800000] / [0.000000, 0.800000] | [0.376095, 0.376095] |
| 1 | 3 | 7 / 0 | 0.016607 | 0.051736 [0.034861, 0.070229] | [0.000000, 0.000000] | [0.000000, 0.000000] / [0.000000, 0.000000] | [0.003246, 0.003246] |
| 1 | 7 | 7 / 0 | 0.038321 | 0.095570 [0.064986, 0.128885] | [0.000000, 0.000000] | [0.000000, 0.000000] / [0.000000, 0.000000] | [0.011001, 0.011001] |
| 1 | 14 | 6 / 1 | 0.075174 | 0.151563 [0.104356, 0.202551] | [0.000000, 0.142857] | [0.000000, 0.000000] / [0.000000, 0.500000] | [0.027407, 0.106718] |
| 2 | 3 | 5 / 0 | 0.032796 | 0.027065 [0.025677, 0.028225] | [0.000000, 0.000000] | [0.000000, 0.000000] / [0.000000, 0.000000] | [0.000735, 0.000735] |
| 2 | 7 | 5 / 0 | 0.074858 | 0.064459 [0.061215, 0.067167] | [0.000000, 0.000000] | [0.000000, 0.000000] / [0.000000, 0.000000] | [0.004167, 0.004167] |
| 2 | 14 | 5 / 0 | 0.144112 | 0.129182 [0.122903, 0.134418] | [0.000000, 0.000000] | [0.000000, 0.000000] / [0.000000, 0.000000] | [0.016732, 0.016732] |

There is no clear pooled conditional benefit. A training fold has only one resolution; observed validation resolution counts are sparse and late uncertainty remains. The per-fold table is descriptive and supports no individual-fold conclusion. Stanford cannot support a recovery serving claim.

## Exports and remaining gates

17 conditional relative-day curves exported and reloaded with exact parity. Unreached quantiles are null: q0.25 17, median 17, q0.75 17. All outputs remain within per-fold supported follow-up; no exact recovery dates or extrapolated quantiles. Research artifact format2 pins native cohort/scale/features/clock and implementation hashes. Every production `predict` call returns `None`.

The private export audit is generated by the runner and independently matches the saved curve count. Public receipts omit source categories from every nested audit, not only the top-level audit. Scientific scores, support, calibration and all private research predictions are byte-for-byte or value-identical to the prior fixed-model run; only publication/provenance metadata changes. Published JSON is byte-identical to its private aggregate; no participant rows, identifiers, predictions or weights are published.

Required clinical/application gates remain: an independently accepted endpoint/split/privacy correction; prospectively ascertained recovery follow-up and calibrated inference on a relevant target population; validated app-native symptoms/artifact integration. Unsupported serving remains unavailable, and #14 is not marked delivered by this research packet.
