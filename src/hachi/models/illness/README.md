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

The committed evidence module rebuilds reports without fitting again:

~~~sh
python -I -m hachi.models.illness.evidence \
  --snapshot "$HACHI_LABEL_SNAPSHOT" --packet-root "$HACHI_ILLNESS_PACKETS" \
  --suffix 002 --previous-suffix 001 --base-python "$HACHI_BASE_PYTHON" \
  --output reports/models/illness
~~~

It validates every saved prediction against the exact validation fold and snapshot
labels/survey predictors, recomputes metrics and paired ablations, rechecks the full
development label grid, and hashes all private packet inputs. A base-only worker
replays artifacts against an archived copy of their exact producing source. The
report discloses threshold redaction and preserves original runner gates. Earlier
run equality is reported only when their packets are supplied. Original scoring
requires a completely clean checkout, including untracked files; use this isolated
worker checkout without generated mail-helper files. Labels-1 must remain retained.

The separately frozen clinical-context exporter streams only admitted standard
Stanford HR/steps. HR hours use the mean of recorded-minute medians, require at
least 30 recorded minutes, and become available only when complete. A native
point is assumed ready at its recorded floating time (steps conservatively one
minute later); actual arrival timestamps do not exist in this archive. Conflicting
duplicates remain unknown. The two complete step-edge interpretations must have
equal totals; steps are absent from the primary model requests.

~~~sh
python -I -m hachi.models.illness.context_export \
  --snapshot "$HACHI_LABEL_SNAPSHOT" --archive "$HACHI_NATIVE_ARCHIVE" \
  --output "$HACHI_RUN_ROOT/illness-clinical-contexts"
~~~

This emits private content-hashed Chronos requests and the agreed
WBM/MOMENT/MeanPool encoder requests: 168 completed HR hours with at least 24
observed hours. Requests contain physiology and units/policy only; identities,
floating cutoffs and inner train/validation roles stay in a separate private join
map. Only development participants with eligible at-risk labels are considered;
outer test is never read. The exporter runs no model or scoring. Frozen encoders
return features; downstream heads, imputation/scaling and any dimensionality
reduction must fit inside the training participants. A complete model-comparison
protocol must be frozen before these features produce scores.

Recheck an existing private packet and regenerate its sanitized public receipt
without repeating native extraction or running inference:

~~~sh
python -I -m hachi.models.illness.context_export \
  --verify-only --snapshot "$HACHI_LABEL_SNAPSHOT" \
  --output "$HACHI_RUN_ROOT/illness-clinical-contexts" \
  --public-report reports/models/illness/clinical-contexts.json
~~~

Verification exercises the actual Chronos request reader, encoder content hashes,
coverage policy, exact development eligibility/fold joins and private permissions.
The public receipt binds both extraction and verification revisions and input
file hashes; arbitrary private-summary fields cannot become public report data.

The frozen representation comparison is configs/experiments/illness/pretrained.json.
It binds the original task/shared protocol and the supported model specifications:
MeanPool76, WBM256, MOMENT1024, and Chronos768 plus its location/scale in bpm.
Chronos request metadata uses24 hours; the encoder sees the same168-hour past
context and this metadata does not change its embedding. Pretraining overlap with
Stanford remains unknown. No PCA or hyperparameter search is introduced. All-missing
inputs and inadequate context-supported fit/calibration people or classes are
unavailable states. Reports must include full-window missingness and identical
common-context comparisons, with no final cross-family winner or opened outer test.
Prior CPU development metrics were already seen; the new feature protocol is
frozen before any representation scores, rather than claiming a blind original study.
