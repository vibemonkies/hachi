# Incident symptom-onset CPU development

This module implements #13's selected-cohort research path. It does not supply
a validated product illness probability. The API continues to answer unavailable.

The at-risk reader consumes the frozen clinical snapshot's 24/48/72-hour
positive/negative labels. Unknown, uncertain, ongoing-episode and washout rows
are excluded. Episode dates attach targets and lead-time intervals only.
Predictors are completed prior-day surveys and optional cutoff-safe external
features; no retrospective outcome/test/category/recovery field enters them.

The shared clinical protocol splits the entire 121-person roster first.
The runner reads outcome/survey rows only for outer-0 development participants.
It has no option to open outer test. Each inner training cohort is split by
participant hash into fit and calibration groups. Fit-only median imputation,
missing indicators, scaling and classifier fitting precede calibration-only
sigmoid fitting and burden-threshold selection. Missing wearable values stay
missing and are imputed inside the fit pipeline, with indicators; the report
retains their extraction coverage. External fitted representations must identify
their fit participants, exclude calibration/held-out people, provide every inner
fold and use identical feature order.

The committed protocol compares prevalence, fixed-C logistic regression and a
small tree with survey history, additional nightly rest and additional anomaly
features. #9 supplies admitted native parsing, both-edge zero-step support and
the robust personal baseline. Its personal history uses only completed,
survey-observed symptom-free prior nights. Unknown survey time never fits a
healthy baseline. The final clinical pretrained comparator remains blocked.

Metrics include AUPRC/AUROC, Brier, reliability bins, window PPV/sensitivity,
incident-event sensitivity, alert episodes, negative-only false-alert episodes
per 30 evaluable negative cutoff-days, and interval-valued lead time.
Participant bootstrap keeps overlapping episode windows together. A later
positive cannot erase an earlier negative-only alert episode. Thresholds sit
between calibration score levels to preserve saved-model alert decisions.

A feature-family run makes only a development selection in fixed candidate
complexity order, requiring positive paired AUPRC uncertainty and the frozen
burden cap; it does not select a final product across all feature families.
Cross-family comparisons remain descriptive until the complete candidate set
and its final evaluation are available.

Run from a clean checkout with uv sync --locked --extra baselines:

~~~sh
python -I -m hachi.models.illness \
  --snapshot "$HACHI_DATA_ROOT/derived/clinical-labels-1-stanford-covid19-wearables-2020-nbe-168d54133c8b" \
  --output "$HACHI_RUN_ROOT/illness-survey"
~~~

For the other frozen families add --feature-family nightly-rest or
--feature-family anomaly-derived and --archive pointing at the admitted
phase1 ZIP. Output directories must be new. Private packets contain canonical
run/split/config documents, data-only calibrated artifacts, source receipts and
predictions (0600 files, 0700 directories). No pickle is read; artifact inference
needs the base installation only. Fitting/metrics require the baselines extra.
The serving document retains unavailable status for all development artifacts.

Stanford coordinates are shifted floating local time represented with Z, not
actual UTC. Survey availability at day end and native-sample availability are
source assumptions. The cohort mixes reported illness categories; it does not
establish a general-cold target. Its observed negative windows all come from
people surveyed around illnesses; the 74 unlabeled controls supply no negatives.
Strong survey-history discrimination can reflect this selection process.
No population prevalence, transportable calibration, real-time availability,
friend-case tuning or clinical deployment is established.

See [the aggregate evidence](../../../../reports/models/illness/phase1.md).
