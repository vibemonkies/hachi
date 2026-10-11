# Recovery research (#14)

This compares a constant daily training-cohort hazard with a discrete-time logistic hazard
using current symptom count, maximum severity and severity sum. The conditional model adds
log future day and fixed ridge 0.1, with scaling from training participants only. Covariates
stay at their landmark values; future symptoms are neither read nor forecast. No wearable
features are used. Recorded wearable-day counts describe actual pairing coverage only.

The locked endpoint is `outcomes-1-sustained-symptom-free-2d`. An event interval `[L,U]`
contributes `S(L-1)-S(U)`; a right-censored observation at `C` contributes `S(C)`. The likelihood
never substitutes interval midpoints, reported recovery dates, or censor dates for exact
resolution dates. This is the daily-bin version of the
[interval-censored likelihood](https://support.sas.com/documentation/cdl/en/imlug/66112/HTML/default/imlug_nonlinearoptexpls_sect035.htm).
Independent observation/censoring is an assumption, not verified by the released surveys.

The first observed symptomatic survey in each episode defines the landmark. Only its score
is used, available at the end of that floating local day. Retrospective onset determines
episode membership and the outcome label; onset, diagnosis, category, tests and eventual
resolution are absent from predictors. No-follow-up episodes, episodes without an observed
symptomatic survey, and landmarks without future follow-up are excluded explicitly.
`clinical.landmarks` is the shared research input builder. Later cutoffs are unvalidated.

The common protocol is owned by the coordinator in
`configs/evaluation/stanford-phase1-clinical.json`; the fixed model/evaluation choices are in
`configs/experiments/recovery/phase1.json`. Both must be committed before scoring. Split the
full 121-person roster into outer4/inner3 folds first, then filter task eligibility. Evaluate
outer0's disjoint inner validation people only. Outer0 test is sealed, with no selection,
refit, or post-hoc calibration. These are shifted floating local dates represented with Z,
**not actual UTC** and never a cross-cohort calendar join.

The primary comparison is the censored negative log probability within seven future daily
bins. Intervals crossing that horizon assert survival only before their first possible day;
an interval starting day1 and extending past the horizon supplies no scoring information.
Calibration reports predicted resolution against identified outcome fraction bounds, Brier
identification bounds, and participant-cluster percentile uncertainty at days3/7/14. Bounds
are wide when intervals or lost follow-up leave the horizon outcome unknown. No unknown
outcomes are turned into negatives. Bootstrap uncertainty conditions on the fitted models
and the chosen outer split; it does not measure all training/selection uncertainty.

Exports stop at at most14 future days and only where at least five distinct training people
have label follow-up through that day. This follow-up rule limits extrapolation; it is not
proof of clinical adequacy or confirmed sustained resolution support. Unreached quantiles
are null. `RecoveryArtifact.research_payload` exports contract-valid relative-day curves;
`RecoveryArtifact.predict` always abstains because these artifacts are research only. The
small Stanford cohort and its inadequate recovery event count remain a required delivery
gate. No serving artifact or clinical accuracy claim is produced.

Run from this exact clean committed worktree, with a private environment and output root:

```sh
UV_PROJECT_ENVIRONMENT="$HOME/hachi/runtime/navyowl/venv" \
UV_CACHE_DIR="$HOME/hachi/runtime/navyowl/cache" \
uv run python -I -m hachi.models.recovery \
  --snapshot "$HOME/hachi/data/derived/clinical-labels-2-stanford-covid19-wearables-2020-nbe-6a864b03b2d3" \
  --config configs/experiments/recovery/phase1.json \
  --output "$HOME/hachi/runs/NavyOwl/recovery-phase1-unique"
```

The output directory must be new and outside the checkout. It contains a private fold plan
and one directory per inner fold: data-only hashed model, canonical run/split/config manifests,
metrics, research predictions/quantiles and serving abstention metadata. Files are mode600;
directories are mode700. `load_artifact` checks the immutable pin, exact file set, checksums,
implementation hashes, dimensions and endpoint/features. The runner reloads each artifact
and checks prediction parity and production abstention. Only `aggregate.json` is sanitized
for publication; models, manifests with participant assignments and predictions remain
private. The aggregate receipt records exact commit, source/config/lock/snapshot/split hashes.

Tests cover analytic likelihood and gradients, the constant hazard's closed-form estimate,
extreme logits, interval truncation, causal landmark availability, episode boundaries,
participant support rather than repeated episodes, calibration unknowns, cluster bootstrap,
private artifact reload, tamper rejection, and serving abstention.
