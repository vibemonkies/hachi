# Baseline implementation — issue #9

This provides data-independent baseline software over canonical observations and
the merged #7 evaluator. Real PMData results, healthy-period alert burden, and the
frozen real protocol remain acceptance gates. Generated examples are software
checks, not evidence of physiological prediction or illness detection.

## Forecast caller

```python
from hachi.models.baselines import BaselineConfig, baseline_factory
from hachi.evaluation import evaluate_forecast

model_config = BaselineConfig(
    method="seasonal_naive",
    metric="heart_rate",
    aggregation="mean",
    max_age_hours=48,
    seasonal_period_hours=24,
)
result = evaluate_forecast(
    split, observations, labels, baseline_factory(model_config), evaluation_config
)
```

Three simple comparators support canonical physiology metrics and their registered
mean/median/min/max aggregation. Completed UTC hourly bins contain only records
available at cutoff. Intervals spanning hours are omitted; sample counts never
claim continuous coverage. Ingestion owns source/unit compatibility and duplicate
resolution. Missing bins and stale history produce abstentions.

- `hourly-last-valid-v1` repeats the latest eligible hourly aggregate.
- `utc-seasonal-naive-v1` repeats the exact latest completed UTC seasonal bin
  for each target phase. Missing phases abstain. A 24-hour UTC season is explicitly
  different from a local calendar day across DST.
- `train-population-mean-v1` fits a mean using completed training hours available
  by the first cutoff, with equal participant weighting. Held-out measurements
  cannot refit it; it abstains when no training hours are eligible.
- `causal-hourly-tree-v1` fits a scikit-learn decision tree to historical
  participant/lead pairs. Features use that origin's available prefix only;
  labels must be complete/available by fitting. Features are last/previous hour,
  prefix mean, observed-hour count, age, UTC target phase and lead. Missing or
  stale prefixes and unsupported leads abstain, without imputation. Training
  examples are weighted equally by participant. Hyperparameters are explicit.

The evaluator controls participant assignment, availability, label separation,
test sealing and coverage denominators. Artifact inference additionally refuses
cutoffs before the fitting instant. Inputs must use the model's metric and
aggregation and the evaluator lookback must support the model's declared policy.

## Saved inference

`fit_baseline`/`fit_tree` return frozen models. `save_artifact` writes a new private
0700 directory with 0600 JSON files and returns the canonical `ArtifactRef`.
`load_artifact(path, expected_reference)` verifies bounded files, content hashes,
the receipt identity and exact baseline source hashes before parsing a versioned
model. Existing directories are never overwritten. Caller storage/admission
controls remain outside this SDK.

Tree artifacts contain bounded, validated leaf/branch data with unique forward
references. Serving matches scikit-learn's float32 feature comparisons and needs
no pickle execution or scikit-learn import. Fitting uses the locked optional
`baselines` extra. The default CPU install and CI contract checks remain separate;
CI also runs the optional model tests explicitly. Private evaluation packets bind
the artifact, dataset/split, model config through the artifact, source, code and
environment. Do not commit fitted models or participant predictions.

## Nightly comparator

`nightly_deviation` uses `NightlyRest` summaries of complete local midnight-to-07:00
windows, declared IANA timezones, actual observed zero-step minutes, event/end and
availability times. Night length follows DST. Vendor daily RHR and absent step
records cannot stand in for these summaries. The source-audited feature adapter
and real nighttime coverage policy remain integration work with #5.

`causal-nightly-mad-v1` uses the median and 1.4826-scaled MAD of eligible prior
local nights, excluding the current night, missing rest measurements and known
confounded nights. It applies an explicit scale floor, minimum-night count and
threshold. Configuration defaults are experiment parameters, not calibrated
clinical thresholds. Incomplete/future nights, missing steps/rest measurements and
cold starts abstain. Only confounders recorded by cutoff are used; callers supply
the requested participant's entries. Current known confounders remain visible.
The output is deviation/abstention, with no illness probability or invented
healthy-period alert burden.

## Upstream NightSignal audit

The [upstream code](https://github.com/StanfordBioinformatics/wearable-infection/blob/99b3bd7937e72d42c2670c7a259d9f9f8728dc06/nightsignal.py)
is Apache-2.0, revision `99b3bd7937e72d42c2670c7a259d9f9f8728dc06`, source SHA-256
`198487887166afa2c7f884d832c2c837d41f2973b684da0303ec5aa8ad54a999`.
It includes the current night in its streaming median and can fill a missing
night from the following night's measurements. The generated full/prefix replay
demonstrates an earlier imputed red alert appearing only after future data arrives.
That behavior cannot be described as an earlier available prediction.

`nightsignal_reproduction.py` executes that exact reviewed source, unchanged, in
new isolated directories on generated Fitbit-format inputs. A documented palette
alias/Agg shim accommodates modern plotting; computation is unchanged. The
compatibility environment is separate from Hachi's model extra and recorded by
its hash-locked package file, versions, source/runner/shim hashes and aggregate
receipt. It does not reproduce the original NumPy 1.18.5/pandas 1.0.4 environment. A separate admitted-example run exercised
both the Fitbit and Apple Watch branches privately; its aggregate receipt is
[evidence/admitted-example-reproduction.json](evidence/admitted-example-reproduction.json).
Both commands exited successfully and produced 305 output nights in total. This
checks code/format execution, not healthy-period alert burden or accuracy. Raw
inputs, dated predictions, and plots remain in private ignored storage with the
source license notice. The robust comparator has its own
id and is not presented as faithful NightSignal.

## Reproduce

```sh
uv sync --locked --extra baselines
uv run --locked --extra baselines pytest tests/models/baselines
npm exec --yes --package=bun@1.4.0 -- make check
uv run --locked --extra baselines python -m hachi.models.baselines.demo --output runs/new-baselines
uv build --out-dir runs/new-baseline-dist
```

The generated walkthrough keeps test participants sealed, evaluates all four
forecast models on the same split/grid, writes versioned artifacts and canonical
run packets, reloads each artifact, and confirms identical predictions and counts.
Only sanitized aggregate receipts belong in Git. Local model files and predictions
stay in ignored private `runs/` directories.

Before closing #9: admit/reconcile #5's real observations and targets; freeze the
scientific inclusion/fold/threshold protocol; run all comparators on #7's real
harness; reproduce upstream on admitted compatible examples; measure observed
healthy-period alert episodes, coverage and confounders; and reproduce selected
artifact inference. No model promotion or real-data acceptance is implied here.

Primary APIs: [tree regressor](https://scikit-learn.org/stable/modules/generated/sklearn.tree.DecisionTreeRegressor.html),
[persistence](https://scikit-learn.org/stable/model_persistence.html), and
[NightSignal paper](https://www.nature.com/articles/s41591-021-01593-2).

### Derived hourly features

The hourly baseline and tree paths also accept #7's internal `HourlyFeature`,
which retains its canonical aggregate, complete-bin readiness and source rule.
Its value is already aggregated: the model preserves it and checks aggregation
compatibility. Native observed count supplies the model sample-count threshold;
#7's explicit policy checks coverage. Mixing raw and derived inputs for the same
metric or giving duplicate derived bins is refused. Saved source receipts bind
`evaluation/features.py`, `evaluation/serialization.py` and `contracts/causality.py`
as well as baseline modules. Archived receipts describe their exact earlier code;
new artifacts must be built for the new implementation.

### Recorded overnight rest input

`nightly_rest(observations, request, policy)` turns one participant's canonical
point HR and complete aligned one-minute step totals into a cutoff-specific
`NightlyRest`. The complete local midnight-to07:00 window follows DST; its minute
denominator is 360/420/480 as appropriate. Filter event end and availability
before computing anything. Query #5's raw reader for this small window; vendor
daily RHR and final-day aggregates are incompatible inputs.

Only actually recorded **zero** step minutes with enough available HR samples
contribute. Missing step minutes remain unknown; positive steps exclude the
minute. Take the median HR within each eligible minute, then the median across
minutes, giving minutes equal weight regardless of sampling density. Prespecify
`NightlyFeaturePolicy(min_hr_samples_per_minute=..., min_rest_minutes=...)`;
these are experimental inclusion choices, not calibrated defaults. Incomplete
nights or too few usable minutes have `rhr_bpm=None`.

The result records the exact request/cutoff, policy, causal input hash and counts
for observed/unobserved step minutes, recorded zero-step minutes lacking HR, low
HR sample counts and usable rest minutes. Only usable HR/zero-step minutes feed
`NightlyRest.observed_zero_step_minutes`, preventing step-only coverage from
passing the robust baseline's gate. Duplicate native events and unsupported step
spans are refused; resolve sources upstream. HR intervals are excluded and
audited by this point-HR adapter. This PMData-compatible path does not claim to
cover variable-duration Apple step records. Recompute for each cutoff; late
records can change a later summary and must not retroactively alter an earlier
summary. Store results privately with the source snapshot/run manifest.

`nightly_deviation(result.night, prior_nights, robust_config, cutoff=...)` keeps
its cold-start/missingness abstention and recorded-confounder policy. Neither
this input nor its deviation score creates healthy labels, measured false-alert
burden, illness probabilities or real-cohort validation evidence.

### Accumulated amounts and durations

The hourly and tree comparators accept registered sums for steps, active energy,
distance and sleep durations as well as level summaries. Recorded zeros are
retained; missing bins are never generated as zeros. Raw overlapping accumulated
intervals are refused, and duration values in hourly inputs and saved mean/tree
artifacts must respect the shared hourly integrity bound. Derived bins preserve
their already-computed sums and native coverage/count provenance.

Partially observed raw sums are observed subtotals. Full-hour total forecasting
requires complete feature/target coverage in the frozen real protocol. The
evaluator's explicit target coverage/count thresholds also govern paired scoring,
so models cannot be compared under different target inclusion rules.
