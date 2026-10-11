# Phase1 incident symptom-onset development

**#13 remains incomplete. Product illness probabilities remain unavailable.** These are retrospective selected-survey-cohort experiments, not population calibration or an all-colds result. Outer test remains sealed.

All three feature families use identical observed at-risk labels and participant-held folds. The target is any reported illness onset; phase1 contains COVID-19, other illness, influenza B and unspecified episodes. The 74 controls outside the label tables supply zero negatives. Every observed negative comes from a participant surveyed around an illness. Survey availability is assumed at the end of its floating local day; Z timestamps do not establish actual UTC or alignment with PMData.

## Frozen protocol and evidence

- Clean scoring source: 722f51ae1d5bdcdd46dbfa594acff872444839a4.
- Protocol: configs/experiments/illness/phase1.toml, SHA 7411de9327a5065affad1fea7905842cae9151b0e6091288f0cc6f227d66b30c; committed before scores.
- Shared clinical protocol SHA 60a4345a6feb8f4a192e6aec718e4b364d2f22a93ad8d227e1645d092ec6e82c.
- Labels-1 snapshot SHA 168d54133c8bc1c566f0b1a023d4f7ca04f54cecbadd3257fa4840e0031e8a33; native archive SHA 52ca976e6c08daa0cf34b6b82f4fc69b8894c1eef66e598efa40197df4e380f4, verified against admission.
- Full 121-person roster; outer 4 / inner 3 / min-train 4 / seed 42 / active outer 0; plan SHA 13dd73b4b3f2b6beabe105c5e577e86e935fa68edfdc117d8e9ebdc7c772fa5e. Each inner fold: 60 training / 30 validation / 31 sealed outer-test participants. Task filters apply after splitting.
- Calibration: 25% hash-held participants inside each inner training cohort. Median imputation, missing indicators, scaling and classifier fitting use fit people only. Sigmoid calibration and thresholds use calibration people only. Inner validation remains untouched until scoring.
- Fixed logistic C=1 and tree depth 2 / leaf size 10; burden cap 1 negative-only false-alert episode per 30 evaluable negative cutoff-days; 1000 whole-participant bootstrap replicates, 95% percentile intervals. Positive windows from the same incident remain together.
- A feature-family development candidate promotes over its current simpler incumbent only with positive paired AUPRC lower bound and validation burden within cap. No final cross-family/product selection is made.
- Recomputed 66,552 label/episode comparisons over 11,092 development cutoffs: 0 mismatches. Saved-artifact base-environment replay: 81 artifacts / 4,464 predictions, 0 alert-decision mismatches; maximum probability difference below 7e-16, no NumPy/sklearn installed.
- Required checks: 470 Python tests plus 5 coordination tests, lint/format/schema/fixtures/generated TypeScript; 17 illness tests with baselines extra. Base illness collection: 1 passed / 2 modules skipped for optional fitting dependencies.

## Eligible validation denominators

| Horizon | Participants | Incidents | Windows | Positive | Negative | Selected prevalence |
|---|---:|---:|---:|---:|---:|---:|
| 24h | 30 | 36 | 170 | 36 | 134 | 0.212 |
| 48h | 30 | 36 | 157 | 72 | 85 | 0.459 |
| 72h | 30 | 36 | 169 | 107 | 62 | 0.633 |

The reports distinguish eligible participants/windows from scored rows and allocated versus label-contributing fit/calibration people. All 27 fold/horizon/candidate fits per family had both classes. At-risk prevalence is a property of these selected windows, not the source population.

## Candidate results

PPV and sensitivity are conditional on these evaluable windows. False burden counts negative-only consecutive daily alerts, so a later onset cannot erase earlier false alerts. Lead times retain the day-precision onset interval;24h predictions offer no guaranteed positive lead time. Full metric intervals, reliability bins, alerted windows/episodes and lead-time uncertainty are in [phase1.json](phase1.json).

### anomaly-derived

| Horizon/model | AUPRC (95% CI) | AUROC | Brier | PPV | Event sensitivity | False episodes/30 negative days |
|---|---:|---:|---:|---:|---:|---:|
| 24h/prevalence | 0.218 [0.118, 0.669] | 0.520 | 0.170 | unestimable | 0.000 | 0.000 |
| 24h/logistic | 0.772 [0.631, 0.915] | 0.945 | 0.073 | 0.828 | 0.667 | 1.119 |
| 24h/tree | 0.761 [0.610, 0.904] | 0.934 | 0.076 | 0.824 | 0.389 | 0.672 |
| 48h/prevalence | 0.451 [0.283, 0.861] | 0.488 | 0.267 | unestimable | 0.000 | 0.000 |
| 48h/logistic | 0.921 [0.851, 0.982] | 0.956 | 0.072 | 0.904 | 0.667 | 1.765 |
| 48h/tree | 0.913 [0.817, 0.987] | 0.956 | 0.049 | 0.917 | 0.472 | 1.059 |
| 72h/prevalence | 0.600 [0.402, 0.947] | 0.433 | 0.284 | unestimable | 0.000 | 0.000 |
| 72h/logistic | 0.969 [0.929, 0.998] | 0.965 | 0.059 | 0.978 | 0.417 | 0.484 |
| 72h/tree | 0.974 [0.937, 0.998] | 0.975 | 0.024 | 0.980 | 0.472 | 0.484 |

### nightly-rest

| Horizon/model | AUPRC (95% CI) | AUROC | Brier | PPV | Event sensitivity | False episodes/30 negative days |
|---|---:|---:|---:|---:|---:|---:|
| 24h/prevalence | 0.218 [0.118, 0.669] | 0.520 | 0.170 | unestimable | 0.000 | 0.000 |
| 24h/logistic | 0.683 [0.447, 0.949] | 0.913 | 0.109 | 0.582 | 0.889 | 2.463 |
| 24h/tree | 0.778 [0.627, 0.919] | 0.937 | 0.070 | 0.840 | 0.583 | 0.896 |
| 48h/prevalence | 0.451 [0.283, 0.861] | 0.488 | 0.267 | unestimable | 0.000 | 0.000 |
| 48h/logistic | 0.930 [0.865, 0.988] | 0.952 | 0.077 | 0.886 | 0.889 | 1.765 |
| 48h/tree | 0.908 [0.836, 0.972] | 0.934 | 0.068 | 0.944 | 0.528 | 0.706 |
| 72h/prevalence | 0.600 [0.402, 0.947] | 0.433 | 0.284 | unestimable | 0.000 | 0.000 |
| 72h/logistic | 0.965 [0.920, 0.997] | 0.955 | 0.065 | 0.962 | 0.750 | 0.968 |
| 72h/tree | 0.961 [0.921, 0.992] | 0.936 | 0.064 | 0.971 | 0.639 | 0.968 |

### survey-history

| Horizon/model | AUPRC (95% CI) | AUROC | Brier | PPV | Event sensitivity | False episodes/30 negative days |
|---|---:|---:|---:|---:|---:|---:|
| 24h/prevalence | 0.218 [0.118, 0.669] | 0.520 | 0.170 | unestimable | 0.000 | 0.000 |
| 24h/logistic | 0.779 [0.643, 0.919] | 0.949 | 0.071 | 0.828 | 0.667 | 1.119 |
| 24h/tree | 0.761 [0.610, 0.904] | 0.934 | 0.076 | 0.824 | 0.389 | 0.672 |
| 48h/prevalence | 0.451 [0.283, 0.861] | 0.488 | 0.267 | unestimable | 0.000 | 0.000 |
| 48h/logistic | 0.922 [0.853, 0.983] | 0.957 | 0.071 | 0.904 | 0.667 | 1.765 |
| 48h/tree | 0.904 [0.831, 0.971] | 0.935 | 0.068 | 0.935 | 0.417 | 0.706 |
| 72h/prevalence | 0.600 [0.402, 0.947] | 0.433 | 0.284 | unestimable | 0.000 | 0.000 |
| 72h/logistic | 0.969 [0.929, 0.998] | 0.965 | 0.058 | 0.978 | 0.417 | 0.484 |
| 72h/tree | 0.960 [0.916, 0.993] | 0.951 | 0.053 | 0.978 | 0.417 | 0.484 |

## Feature ablations

Additional rest/anomaly features are compared against the same survey-history candidate on identical ordered windows. These paired differences are descriptive development ablations; they do not unlock serving.

| Added family/horizon/model | Paired AUPRC difference (95% CI) |
|---|---:|
| anomaly-derived/24h/logistic | -0.007 [-0.020, 0.006] |
| anomaly-derived/24h/tree | 0.000 [0.000, 0.000] |
| anomaly-derived/48h/logistic | -0.001 [-0.003, 0.000] |
| anomaly-derived/48h/tree | 0.009 [-0.040, 0.054] |
| anomaly-derived/72h/logistic | 0.000 [0.000, 0.000] |
| anomaly-derived/72h/tree | 0.014 [0.000, 0.038] |
| nightly-rest/24h/logistic | -0.096 [-0.272, 0.077] |
| nightly-rest/24h/tree | 0.017 [-0.008, 0.059] |
| nightly-rest/48h/logistic | 0.008 [-0.017, 0.041] |
| nightly-rest/48h/tree | 0.004 [-0.021, 0.037] |
| nightly-rest/72h/logistic | -0.004 [-0.022, 0.009] |
| nightly-rest/72h/tree | 0.001 [-0.024, 0.027] |

Native extraction includes 240 distinct eligible subject cutoffs across all horizons: 123 observed rest measurements / 117 missing; anomaly 20 scored / 103 cold-start / 117 missing. Missing features remain missing and enter fit-only imputation with indicators; full-window classification scores therefore are not an anomaly coverage claim. Rest requires 30 quiet minutes under both minute-edge interpretations. Robust personal history uses only prior completed surveyed symptom-free nights, never retrospective outcome metadata.

## Commands and private artifacts

Environment: Python 3.12.13 / scikit-learn 1.9.1 from the locked baselines extra; Bun 1.4.0 for frozen contract checks. No root dependency or shared-contract changes.

On clean scoring source 722f51a, with the worktree-owned environment:

~~~sh
.venv/bin/python -I -m hachi.models.illness --snapshot "$HOME/hachi/data/derived/clinical-labels-1-stanford-covid19-wearables-2020-nbe-168d54133c8b" --output "$HOME/hachi/runs/PlumJay/illness-phase1/survey-history-002"
~~~

The nightly-rest and anomaly-derived runs add the matching --feature-family and --archive "$HOME/hachi/data/stanford-covid19-wearables/2020-nbe/COVID-19-Wearables.zip" and use distinct nightly-rest-002/anomaly-derived-002 output roots. New reproductions must use new directories. Runtime in the private summary excludes native extraction; cohort/job elapsed time additionally depends on source parsing and concurrent CPU work.

Private packet roots: /Users/ezzyrappeport/hachi/runs/PlumJay/illness-phase1/{survey-history,nightly-rest,anomaly-derived}-002. Each contains canonical run/split/config documents, data-only models and source/hash receipts, private predictions and training partitions. Models and predictions stay outside Git/GitHub/mail; files 0600 / directories 0700. Aggregate artifact refs and replay checks are in the JSON report. serving.json remains unavailable.

## Remaining gates

- A clinical pretrained-feature comparator on the same floating-clock folds/cutoffs. PMData features cannot be joined to shifted Stanford dates; #11/#12 interfaces alone are not a completed comparison.
- More independently observed negatives and enough events to establish transferable calibration. High survey-history discrimination can reflect illness-centered observation/participation, and cannot support population-risk claims.
- Complete candidate selection/calibration freeze and one untouched outer-test evaluation, followed by independently reproduced causal API/artifact inference.
- Upstream CMU registration/additional-cohort access where needed. No CMU, DREAMT/GLOBEM/CovIdentify shared-account analysis or friend-case tuning occurred.
