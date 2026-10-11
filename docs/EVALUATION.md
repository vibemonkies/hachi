# Evaluation protocol

Freeze this protocol, task labels, split manifests, and metric definitions before opening the test set. Scores are not meaningful without the denominator, number of participants/episodes, and exact target.

## Population and chronological separation

1. Assign whole participants to training, validation, and test. With small cohorts, use grouped/nested cross-validation and report uncertainty rather than one lucky split.
2. Use rolling-origin cutoffs within each evaluation subject. Only records available at cutoff enter features, imputation, baseline estimation, or personalization.
3. Separate forecast labels after cutoff. Purge overlapping target windows at boundaries and group illness episodes together. Report sensitivity to lookback/embargo choices.
4. Fit feature selection, scaling, hyperparameters, alert thresholds, and probability calibration on training/validation only. Stacking uses out-of-fold training predictions, never in-sample predictions.
5. Hold the final test cohort untouched until selection is frozen. Record pretrained training-cohort overlap where known; unknown overlap is a limitation.
6. Public cohort evaluation and personal Apple Watch transfer are different experiments. Report device/source shifts and missing channels. No claim that Fitbit performance establishes Apple Watch performance.

## Label discipline

Illness target: a newly documented symptom-onset interval falling after cutoff and within the specified horizon; ongoing episodes are excluded from onset prediction. Positive tests can define a separate target, but cannot silently replace onset. No survey is unknown, not healthy. Prespecify episode separation, uncertain onset handling, and confounders such as exercise, vaccination, alcohol, travel, and sleep loss.

Recovery target: define symptom resolution (for example, a sustained prespecified low-symptom interval) from the actual source codebook. Right-censor follow-up that ends before resolution. A short observation period cannot establish eventual recovery; do not train exact recovery-day labels from it. Self-reported improvement and complete resolution are distinct outcomes.

Alertness: a daily fatigue score is not an hourly energy curve. Ratings and reaction-time observations need event time, collection time, and consistent scales. Observational prediction does not prove the causal effect of changing bedtime; scenario outputs keep their assumptions visible.

## Comparators and metrics

| Task | Comparators | Required report |
|---|---|---|
| Physiology | Last valid value, seasonal naive, train-only personal/population mean, tree model | MAE/RMSE per metric and participant, pinball loss, interval coverage/width, coverage exclusions |
| Anomaly | Causal robust baseline and faithful NightSignal comparison where compatible | False-alert episodes per 30 observed healthy days, alerted-day fraction, detection lead time, missingness and confounder breakdown |
| Illness | Prevalence, logistic/tree model, anomaly-derived comparator | AUPRC with prevalence, AUROC, sensitivity/PPV at prespecified alert burden, Brier score/reliability plot, event lead time |
| Recovery | Training-cohort survival/episode-duration baseline | Censoring-aware Brier score, discrimination, interval coverage where estimable, subgroup/event counts |
| Alertness | Last rating, time-of-day mean, unpersonalized circadian model | MAE/correlation on held-out observed ratings/PVT, coverage; simulation assumptions separately |

Bootstrap at participant level, not individual rows. Report uncertainty, excluded observations, abstention rate, and performance conditional on coverage. Sparse labels may make a metric unestimable; report that directly.

No invented accuracy threshold. Before test evaluation, select the primary metric and operational alert burden on validation. A more complex model is promoted only when its paired improvement and operational cost justify it; otherwise select the baseline and retain the negative experiment. To claim improvement, report the paired difference and uncertainty, not only a favorable point estimate.

## Experiments in order

1. Data audit and frozen split manifest.
2. Simple physiology and anomaly baselines.
3. Zero-shot pretrained forecast and frozen wearable representations.
4. Trained head or targeted fine-tuning with early stopping on validation.
5. Ablations: additional channels, representation contribution, personalization, ensemble versus best member.
6. Calibration/coverage policy frozen; one final held-out evaluation.
7. Export selected artifact, reproduce inference from a fresh environment, then run app replay.

## Friend's later Apple Watch case study

- Obtain the friend's permission for processing and separately for any presentation. Keep raw files, exact dates, and symptom notes out of GitHub.
- Have the friend record symptom onset and uncertainty before anyone views predictions. A person who already knows the illness cannot provide a fully blinded prospective trial; name it a retrospective held-out case study.
- A teammate holds the full export and outcome record. Freeze model, preprocessing, baseline policy, thresholds, and cutoffs before unsealing the withheld tail.
- Replay several prespecified cutoffs (for example 72, 48, and 24 hours before onset), plus earlier healthy periods. Cutoffs use the recorded onset interval, not a peak chosen after plotting results.
- Remove the tail before all transformations. Exclude records created after cutoff even if backdated; report when true historical availability cannot be reconstructed from an export. Derived sleep/session summaries must be complete by cutoff.
- Save signed/hashed prediction artifacts before revealing later data. No tuning on this case. Preserve failed detections and false alerts.
- Report one person's lead times, trajectories, missingness, and alert history. Do not derive population sensitivity, clinical accuracy, or generalization from this episode.

## Evidence packet

Every model PR includes command/configuration, commit SHA, environment, source/checkpoint revisions and checksums, dataset/split hashes, counts, baseline comparison, confidence intervals, runtime/memory, and artifact location. Commit only reviewed aggregate reports. Private per-subject predictions remain in approved storage. Notebook screenshots alone do not close a model issue.
