# Phase1 incident symptom-onset development

**#13 remains incomplete. Product illness probabilities remain unavailable. Outer test sealed.**

The target is any reported illness onset in a selected retrospective cohort mixing COVID-19, other illness, influenza B and unspecified episodes. This does not establish population calibration or an all-colds model. The 74 unlabeled controls supply zero negatives. Every observed negative comes from illness-reporting people surveyed around their illnesses.

A negative label requires completed symptom-free surveys throughout the future window. Prior survey completion predicts future completion: past-survey features can rank negative-eligible windows without an illness signal. The causal availability rule prevents future predictors, but it does not remove this outcome-observation selection. At the survey-history ceiling and with only 62 negatives at 72h, these ablations cannot establish whether physiology carries independent signal.

## Frozen protocol and provenance

- Clean scoring source: 722f51ae1d5bdcdd46dbfa594acff872444839a4; report-producing code: 2db1651447e4b4b19abe372d1b9c9d9858457c83.
- Frozen task protocol SHA 7411de9327a5065affad1fea7905842cae9151b0e6091288f0cc6f227d66b30c; shared protocol SHA 60a4345a6feb8f4a192e6aec718e4b364d2f22a93ad8d227e1645d092ec6e82c.
- Labels-1 snapshot SHA 168d54133c8bc1c566f0b1a023d4f7ca04f54cecbadd3257fa4840e0031e8a33; labels-1 must remain retained for this pinned experiment. Labels-2 has identical task tables but is not accepted by this task protocol.
- Full roster: 121 people, outer4/inner3/mintrain4/seed42/activeouter0; plan SHA 13dd73b4b3f2b6beabe105c5e577e86e935fa68edfdc117d8e9ebdc7c772fa5e. Each inner fold allocates 60 training / 30 validation / 31 sealed test people before task eligibility.
- Calibration uses 15/15/15 hash-held allocated people per inner training fold; only 5/6/5 contribute labels. Fit-only imputation/scaling/classifiers precede calibration-only sigmoid/threshold fitting. These small cohorts do not establish transferable calibration.
- Frozen logistic C1, tree depth2/leaf10, calibration C1; cap 1 negative-only false-alert episode per 30 evaluable negative cutoff-days; 1000 whole-participant bootstrap replicates and 95% intervals.
- Label-grid recheck: 11,092 development cutoffs / 66,552 comparisons / 0 mismatches. Base-only replay: 81 artifacts / 4,464 predictions / 0 decisions differ / max probability delta 6.66e-16.
- Input file hashes, assembly/worker source hashes, exact producing revisions and source-only rerun reconciliation are in phase1.json. Operational thresholds are explicitly redacted; runner gates remain unchanged and delivered comparison status is separately derived by the assembly.
- Prior-run reconciliation: survey-history-001 at 4ac23a9cdfcafd024a77de3bd6eb8d250f812c8b versus survey-history-002 at 722f51ae1d5bdcdd46dbfa594acff872444839a4: protocols/folds/labels/aggregate metrics/selections identical; nightly-rest-001 at 4ac23a9cdfcafd024a77de3bd6eb8d250f812c8b versus nightly-rest-002 at 722f51ae1d5bdcdd46dbfa594acff872444839a4: protocols/folds/labels/aggregate metrics/selections identical; anomaly-derived-001 at 4ac23a9cdfcafd024a77de3bd6eb8d250f812c8b versus anomaly-derived-002 at 722f51ae1d5bdcdd46dbfa594acff872444839a4: protocols/folds/labels/aggregate metrics/selections identical
- Original -001 to -002 source change: lazy optional-dependency imports and TYPE_CHECKING packaging; no scientific feature/calibration/selection setting changed. Changed source paths are recorded beside the verified aggregate equality.

## Eligible validation denominators

| Horizon | People | Incidents | Windows | Positive | Negative | Prevalence |
|---|---:|---:|---:|---:|---:|---:|
| 24h | 30 | 36 | 170 | 36 | 134 | 0.212 |
| 48h | 30 | 36 | 157 | 72 | 85 | 0.459 |
| 72h | 30 | 36 | 169 | 107 | 62 | 0.633 |

## Past-survey observation by label

| Horizon/label | Windows | Zero prior 7-day surveys | Fraction |
|---|---:|---:|---:|
| 24h/positive | 36 | 33 | 0.917 |
| 24h/negative | 134 | 9 | 0.067 |
| 48h/positive | 72 | 67 | 0.931 |
| 48h/negative | 85 | 6 | 0.071 |
| 72h/positive | 107 | 101 | 0.944 |
| 72h/negative | 62 | 3 | 0.048 |

## Candidate results

Metrics are pooled across held-out inner validation people. The prevalence model assigns a different constant per fold; its pooled AUROC reflects cross-fold constants, not within-fold ranking. Within each fold it has one probability value (AUROC 0.5 when both classes exist). PPV/sensitivity/burden are conditional on evaluable windows, not population healthy time. Lead-time bounds retain the day-precision onset interval; 24h has no guaranteed positive lead time.

Calibration burden thresholds fail to transfer: 7 of 18 non-prevalence family/horizon fits exceed the validation point cap, and burden intervals span the cap even for several point estimates that pass. No transferable burden guarantee is demonstrated. Full reliability, sensitivity, lead-time and burden intervals remain in phase1.json.

### anomaly-derived

| Horizon/model | AUPRC (95% CI) | AUROC | Brier | PPV | Event sensitivity | False episodes/30 negative days (95% CI) |
|---|---:|---:|---:|---:|---:|---:|
| 24h/logistic | 0.772 [0.631, 0.915] | 0.945 | 0.073 | 0.828 | 0.667 | 1.119 [0.539, 2.432] |
| 24h/prevalence | 0.218 [0.118, 0.669] | 0.520 | 0.170 | unestimable | 0.000 | 0.000 [0.000, 0.000] |
| 24h/tree | 0.761 [0.610, 0.904] | 0.934 | 0.076 | 0.824 | 0.389 | 0.672 [0.000, 1.623] |
| 48h/logistic | 0.921 [0.851, 0.982] | 0.956 | 0.072 | 0.904 | 0.667 | 1.765 [0.312, 4.840] |
| 48h/prevalence | 0.451 [0.283, 0.861] | 0.488 | 0.267 | unestimable | 0.000 | 0.000 [0.000, 0.000] |
| 48h/tree | 0.913 [0.817, 0.987] | 0.956 | 0.049 | 0.917 | 0.472 | 1.059 [0.000, 3.914] |
| 72h/logistic | 0.969 [0.929, 0.998] | 0.965 | 0.059 | 0.978 | 0.417 | 0.484 [0.000, 3.343] |
| 72h/prevalence | 0.600 [0.402, 0.947] | 0.433 | 0.284 | unestimable | 0.000 | 0.000 [0.000, 0.000] |
| 72h/tree | 0.974 [0.937, 0.998] | 0.975 | 0.024 | 0.980 | 0.472 | 0.484 [0.000, 3.343] |

### nightly-rest

| Horizon/model | AUPRC (95% CI) | AUROC | Brier | PPV | Event sensitivity | False episodes/30 negative days (95% CI) |
|---|---:|---:|---:|---:|---:|---:|
| 24h/logistic | 0.683 [0.447, 0.949] | 0.913 | 0.109 | 0.582 | 0.889 | 2.463 [1.154, 4.390] |
| 24h/prevalence | 0.218 [0.118, 0.669] | 0.520 | 0.170 | unestimable | 0.000 | 0.000 [0.000, 0.000] |
| 24h/tree | 0.778 [0.627, 0.919] | 0.937 | 0.070 | 0.840 | 0.583 | 0.896 [0.326, 1.837] |
| 48h/logistic | 0.930 [0.865, 0.988] | 0.952 | 0.077 | 0.886 | 0.889 | 1.765 [0.312, 4.840] |
| 48h/prevalence | 0.451 [0.283, 0.861] | 0.488 | 0.267 | unestimable | 0.000 | 0.000 [0.000, 0.000] |
| 48h/tree | 0.908 [0.836, 0.972] | 0.934 | 0.068 | 0.944 | 0.528 | 0.706 [0.000, 2.885] |
| 72h/logistic | 0.965 [0.920, 0.997] | 0.955 | 0.065 | 0.962 | 0.750 | 0.968 [0.000, 3.750] |
| 72h/prevalence | 0.600 [0.402, 0.947] | 0.433 | 0.284 | unestimable | 0.000 | 0.000 [0.000, 0.000] |
| 72h/tree | 0.961 [0.921, 0.992] | 0.936 | 0.064 | 0.971 | 0.639 | 0.968 [0.000, 3.750] |

### survey-history

| Horizon/model | AUPRC (95% CI) | AUROC | Brier | PPV | Event sensitivity | False episodes/30 negative days (95% CI) |
|---|---:|---:|---:|---:|---:|---:|
| 24h/logistic | 0.779 [0.643, 0.919] | 0.949 | 0.071 | 0.828 | 0.667 | 1.119 [0.539, 2.432] |
| 24h/prevalence | 0.218 [0.118, 0.669] | 0.520 | 0.170 | unestimable | 0.000 | 0.000 [0.000, 0.000] |
| 24h/tree | 0.761 [0.610, 0.904] | 0.934 | 0.076 | 0.824 | 0.389 | 0.672 [0.000, 1.623] |
| 48h/logistic | 0.922 [0.853, 0.983] | 0.957 | 0.071 | 0.904 | 0.667 | 1.765 [0.312, 4.840] |
| 48h/prevalence | 0.451 [0.283, 0.861] | 0.488 | 0.267 | unestimable | 0.000 | 0.000 [0.000, 0.000] |
| 48h/tree | 0.904 [0.831, 0.971] | 0.935 | 0.068 | 0.935 | 0.417 | 0.706 [0.000, 2.885] |
| 72h/logistic | 0.969 [0.929, 0.998] | 0.965 | 0.058 | 0.978 | 0.417 | 0.484 [0.000, 3.343] |
| 72h/prevalence | 0.600 [0.402, 0.947] | 0.433 | 0.284 | unestimable | 0.000 | 0.000 [0.000, 0.000] |
| 72h/tree | 0.960 [0.916, 0.993] | 0.951 | 0.053 | 0.978 | 0.417 | 0.484 [0.000, 3.343] |

## Development selections

These candidates were selected using these validation metrics. Their displayed validation performance is therefore optimistic for selection; it is not a final held-out estimate. No cross-family product winner was selected.

| Family | 24h | 48h | 72h |
|---|---|---|---|
| anomaly-derived | tree | prevalence | logistic |
| nightly-rest | tree | tree | logistic |
| survey-history | tree | tree | logistic |

## Descriptive feature ablations

| Added family/horizon/model | Paired AUPRC difference (95% CI) |
|---|---:|
| nightly-rest/24h/logistic | -0.096 [-0.272, 0.077] |
| nightly-rest/24h/tree | 0.017 [-0.008, 0.059] |
| nightly-rest/48h/logistic | 0.008 [-0.017, 0.041] |
| nightly-rest/48h/tree | 0.004 [-0.021, 0.037] |
| nightly-rest/72h/logistic | -0.004 [-0.022, 0.009] |
| nightly-rest/72h/tree | 0.001 [-0.024, 0.027] |
| anomaly-derived/24h/logistic | -0.007 [-0.020, 0.006] |
| anomaly-derived/24h/tree | 0.000 [0.000, 0.000] |
| anomaly-derived/48h/logistic | -0.001 [-0.003, 0.000] |
| anomaly-derived/48h/tree | 0.009 [-0.040, 0.054] |
| anomaly-derived/72h/logistic | 0.000 [0.000, 0.000] |
| anomaly-derived/72h/tree | 0.014 [0.000, 0.038] |

No strictly positive lower bound establishes added physiology at these selected windows. This is insufficient evidence about physiology, not evidence of no physiological signal. Native extraction: 240 eligible distinct cutoffs, 123 observed rest/117 missing; anomaly 20 scored/103 cold-start/117 missing. Missing values remain missing until fit-only imputation; classification coverage is not native anomaly coverage.

## Reproduction and private artifacts

Run scoring at the exact pinned clean revision using the retained labels-1 snapshot and admitted native archive. All raw samples, participant joins, learned models, predictions and thresholds remain private (0700 directories/0600 files). Survey availability is end of its shifted floating day; Z coordinates do not establish actual UTC, arrival timestamps or alignment with PMData.

After scoring, use the committed evidence command with a baselines environment and a separate locked base-only interpreter. It archives the exact scoring source for receipt-checked replay, avoiding a source-pin bypass when the report code changes:

~~~sh
python -I -m hachi.models.illness.evidence --snapshot "$HACHI_LABEL_SNAPSHOT" --packet-root "$HACHI_ILLNESS_PACKETS" --suffix 002 --previous-suffix 001 --base-python "$HACHI_BASE_PYTHON" --output reports/models/illness
~~~

The current report never refits models or opens outer test. A new scoring run requires a new private directory and the original frozen protocol. serving.json remains unavailable. Full-project checks and CI are integration evidence, not population accuracy.

## Remaining gates

- Clinical pretrained-feature comparator on same floating-clock folds/cutoffs.
- Adequate independently observed negatives and calibration cohort.
- Frozen complete-candidate final selection and one outer-test evaluation.
- Validated causal serving input and independent API replay.

CMU labels now exist but have no wearables and cannot supply this wearable model. CovIdentify/Homekit2020/Evidation are unavailable for this task; no adequately sized independent wearable illness cohort has been obtained. No forbidden shared-account dataset analysis or friend-case tuning occurred.
