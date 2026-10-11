# Recovery research (#14)

This compares a constant daily training-cohort hazard with a discrete-time logistic hazard.
Stanford uses current symptom count, maximum severity and severity sum; CMU uses its native
baseline-adjusted eight-item Jackson score. The conditional model adds log future day and
fixed ridge 0.1, with scaling from training participants only. Covariates
stay at their landmark values; future symptoms are neither read nor forecast. No wearable
features are used. Recorded wearable-day counts describe actual pairing coverage only.

The locked endpoint is `outcomes-1-sustained-symptom-free-2d`. An event interval `[L,U]`
contributes `S(L-1)-S(U)`; a right-censored observation at `C` contributes `S(C)`. The likelihood
never substitutes interval midpoints, reported recovery dates, or censor dates for exact
resolution dates. The last answered survey day is observation extent, not necessarily a
censor bound. A lone final free day can begin an eventual qualifying two-day run. Censor
only through the last observed symptomatic or intermediate day in the episode, conservatively
retaining uncertainty across gaps. Exclude zero remaining follow-up. This is the daily-bin
version of the
[interval-censored likelihood](https://support.sas.com/documentation/cdl/en/imlug/66112/HTML/default/imlug_nonlinearoptexpls_sect035.htm).
Independent observation/censoring is an assumption, not verified by the released surveys.

The first observed symptomatic survey in each episode defines the landmark. Only its score
is used, available at the end of its dataset day. Retrospective onset determines
episode membership and the outcome label; onset, diagnosis, category, tests and eventual
resolution are absent from predictors. No-follow-up episodes, episodes without an observed
symptomatic survey, and landmarks without future follow-up are excluded explicitly.
`clinical.landmarks` is the shared research input builder. Later cutoffs are unvalidated.

The common protocol is owned by the coordinator in
`configs/evaluation/stanford-phase1-clinical.json`; the fixed model/evaluation choices are in
`configs/experiments/recovery/phase1.json`. Both must be committed before scoring. Split the
full roster into outer4/inner3 folds first, then filter task eligibility. Evaluate outer0's
disjoint inner validation people only. The corrected runner reads no outer-test outcomes,
and performs no selection, refit, or post-hoc calibration. A previous whole-roster audit
exposed Stanford test aggregates: historical blinding is compromised and cannot be repaired
by removing the report. The af7e26b packet is invalid and superseded. These are shifted
floating local dates represented with Z,
**not actual UTC** and never a cross-cohort calendar join.

Stanford's primary comparison is the censored negative log probability within seven future daily
bins. Intervals crossing that horizon assert survival only before their first possible day;
an interval starting day1 and extending past the horizon supplies no scoring information.
Calibration reports predicted resolution against identified outcome fraction bounds, Brier
identification bounds, and participant-cluster percentile uncertainty at days3/7/14. Bounds
are wide when intervals or lost follow-up leave the horizon outcome unknown. No unknown
outcomes are turned into negatives. Bootstrap uncertainty conditions on the fitted models
and the chosen outer split; it does not measure all training/selection uncertainty.

Stanford exports stop at at most14 future days and only where at least five distinct training people
have label follow-up through that day. This follow-up rule limits extrapolation; it is not
proof of clinical adequacy or confirmed sustained resolution support. Unreached quantiles
are null. `RecoveryArtifact.research_payload` exports contract-valid relative-day curves;
`RecoveryArtifact.predict` always abstains because these artifacts are research only. The
original one-resolved-training-episode gate is retained for comparability and can yield thin
fits; its label-extent support can overstate known at-risk support for wide intervals. The
receipt separately reports training known-at-risk counts and resolved events by day. The
small Stanford cohort and its inadequate recovery event count remain a required delivery
gate. No serving artifact or clinical accuracy claim is produced.

CMU has a separate protocol in `configs/experiments/recovery/cmu.json` and a separate frozen
whole-person split in `cmu-split.json`. Its clock is relative to challenge, never a calendar
alignment. Quarantine follow-up is only five days (six for influenza), so the primary
comparison is fixed at two future days, calibration at days1/2/3, and exports at most three
days. Each exported day requires at least20 distinct training participants known at risk
through that day: censor bound >= day or event interval lower bound > day. Each training fold
requires at least20 resolved episodes. These conservative research support thresholds are
frozen before outcomes/scores and do not establish clinical adequacy. The model has three
coefficients (intercept, log day, Jackson score); fitting policy matches Stanford. There is
no 7/14-day transfer, app-severity conversion, wearable/date/serology joining, or held-out
test scoring. CMU results are a source-specific challenge-cohort comparison.

Calibration identification bounds preserve unknown outcomes. The cluster bootstrap is
descriptive for small folds and conditions on the fitted models. Horizon-straddling interval
coarsening assumes non-informative observation. Eligibility requires retrospective episode
ascertainment and future follow-up, so this comparison is not a prospective deployment trial.
The constant versus log-day-plus-symptom comparison cannot isolate the symptom contribution.

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
Every support/eligibility count is computed on development partitions inside the runner;
no full-roster eligible-outcome counts are published. `private_export_audit` is generated by
the same run, not appended afterward. Research artifact format2 includes its native cohort,
clock and predictor schema; old artifacts do not satisfy the corrected format.

Publication receipt format3 allowlists only recovery-task eligibility and task-specific
exclusions in development and per-fold audits. Canonical/source endpoint categories and
no-follow-up totals stay in private `private-audit.json`; future audit categories remain
private by default. Previously publishing CMU development categories alongside #8's
source-wide totals made test-partition outcome totals derivable. Both cohorts now record
historical aggregate exposure. Eligibility still correlates with #8's source categories,
so residual test-label totals remain roughly inferable from those existing source-wide
audits. Minimization cannot restore past blinding. No test-total subtraction is performed.
CMU protocol version2 changes exposure metadata only; original pre-score model, split,
predictors and short-horizon choices remain unchanged.

Tests cover analytic likelihood and gradients, the constant hazard's closed-form estimate,
extreme logits, interval truncation, causal landmark availability, episode boundaries,
participant support rather than repeated episodes, calibration unknowns, cluster bootstrap,
private artifact reload, tamper rejection, and serving abstention.
