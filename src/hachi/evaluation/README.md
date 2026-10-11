# Issue #7 — CPU evaluation groundwork

This implements the data-independent portion of #7, continued from NobleBadger's existing work without modifying its original checkout. The real-cohort
acceptance gate remains **blocked on #5 PMData**. Synthetic results demonstrate
software behavior, not forecast accuracy or real-data integration.

## Caller and boundaries

Use the merged canonical `Observation`, `Aggregate`, `SplitManifest`, and
`RunManifest` models. No generated schema, fixture, dependency, or root lockfile is changed.
The shared causal helper accepts a read-only timestamp Protocol with unchanged
UTC cutoff guard and event-end/availability comparisons.
The models in `forecast.py` are internal experiment configuration and estimates,
not new API DTOs.

```python
from hachi.evaluation import evaluate_forecast, partition_participants

# Expand these fields in a canonical SplitManifest; choose counts explicitly.
partitions = partition_participants(
    participant_roster,
    seed=42,
    validation_count=3,
    test_count=3,
    exclusions=canonical_exclusions,
)


def fit_model(training):
    # Only training subjects, censored at the FIRST evaluation cutoff.
    fitted = fit_preprocessor_and_model(training.observations)

    def predict(request):
        # One ForecastEstimate (or None for abstention) per target TimeWindow.
        # request.history contains only this participant's eligible prefix.
        # No future Aggregate labels or their missingness are passed here.
        return fitted.predict(request.history, request.targets)

    return predict


result = evaluate_forecast(split_manifest, observations, targets, fit_model, config)
```

Caller-provided model code must not capture the uncensored dataset in a closure,
load it independently, refit on evaluation inputs, or carry learned state between
evaluation participants. The predictor must keep training-fitted parameters
frozen; personal features are derived from that request's prefix only.
This API limits the supplied inputs; it cannot sandbox
arbitrary Python model code. Availability assumptions must already be documented
by ingestion. Dataset snapshot identity is supplied by the caller; the evaluator
checks dataset IDs and roster membership, not upstream archive checksums.

## Invariants

- Participant assignment uses a seeded SHA-256 rank, independent of input order.
  Explicit whole-participant and record exclusions are retained. Duplicate IDs,
  invalid partition counts, and unknown exclusion subjects are refused.
- The native split manifest rejects participant intersections. Test evaluation
  is refused until the caller supplies `test_opened_at_utc` in a new manifest.
  This is an explicit protocol gate, not proof that external selection is frozen.
- Cutoffs and complete target windows lie within `evaluation_window`; the first
  cutoff is its start. `embargo_hours` delays the first target after each cutoff.
  Overlapping target horizons are purged deterministically without examining
  labels. Retained origins are replayed chronologically across participants.
  Each retained origin gets one-hour windows, including missing bins.
- Training preprocessing sees only training observations that ended and became
  available by the first cutoff. Training is frozen for later rolling origins.
  Per-participant history must also start inside the lookback and satisfy the
  shared `available_by` rule. Backdated entries and incomplete intervals cannot
  inform earlier predictions.
- `min_history_hours` means distinct UTC hourly start bins with eligible records
  in `[cutoff - lookback, cutoff)`, not sample count or claimed full-hour coverage.
  Intervals crossing the lookback boundary are conservatively omitted. Sample
  density and source-specific coverage policies remain ingestion/model concerns.
- `population_only` passes no held-out personal history to the predictor;
  `causal_prefix` explicitly permits that subject's available prefix. Both retain
  the prespecified minimum-history inclusion policy. Cohort-overlap status and
  its evidence/limitation note are required in the experiment config.
- Forecast targets are hourly aggregates for one level metric/aggregation.
  Bare aggregates lack availability timestamps and remain **labels only**.
  `HourlyFeature` wraps an observed canonical hourly aggregate with readiness
  and its documented source availability rule. Raw and derived inputs for the
  selected metric cannot be mixed, and derived aggregation must match config.
- Counts reconcile expected retained target bins to scored, missing-label,
  labeled abstention, or insufficient-history points. Scheduler purges are
  reported separately by origin. A missing label never becomes zero or healthy.
- MAE, RMSE, and median (0.5) pinball loss are computed per participant, then
  averaged with equal participant weight. Bootstrap draws resample participants;
  a single participant has no estimable between-participant CI. Interval coverage
  and width are conditional on scored points with supplied intervals. No nominal
  interval coverage or calibrated accuracy claim is invented.

## Availability-preserving hourly view

The internal `HourlyFeature` preserves the complete canonical `Aggregate`,
including coverage, native observed count, source IDs, pipeline version and timezone.
It requires a non-missing level value on a UTC whole-hour grid and UTC readiness
at or after bin end. It is not a canonical source `Observation` or a new wire DTO.
Its derived record ID hashes only that bin and its readiness/rule, never the whole
snapshot: withheld future rows must not alter earlier input identities.

```python
from hachi.evaluation import HourlyFeaturePolicy, hourly_features
from hachi.data.pmdata import iter_aggregates  # supplied by #5

policy = HourlyFeaturePolicy(
    metric="heart_rate",
    aggregation="mean",
    min_coverage=prespecified_coverage,
    min_observed_count=prespecified_native_count,
    availability_rule=documented_source_availability_rule,
)
view = hourly_features(iter_aggregates(snapshot, "hour", metrics=["heart_rate"]), policy)
result = evaluate_forecast(split_manifest, view.features, targets, fit_model, config)
# Persist view.policy and view.counts beside the private run packet.
```

The loader's `FeatureBin(aggregate, available_at_utc)` named tuple implements the
structural input interface. It must guarantee that recomputation at **every** cutoff
at or after readiness gives the stored value and coverage, including coverage-span
availability. The consumer enforces timestamps; it cannot prove this upstream
causal guarantee from a final aggregate alone. #5 owns its recomputation tests.

The explicit inclusion policy gives exclusive counts for included, missing,
low-coverage, low-count, other-metric and other-aggregation bins. Missingness stays
missing. Duplicate selected bins are refused. Scientific thresholds remain to be
frozen against the admitted real cohort; these tests establish software behavior.
Canonical hourly labels retain missing bins separately from feature selection.

Record exclusions in derived mode must identify derived feature IDs. Raw record
quarantines must be applied **before** aggregation; the evaluator refuses unmatched
record exclusions rather than pretending to subtract a raw row from a mean.
Whole-participant exclusions retain their existing behavior. A pre-excluded snapshot
must document raw exclusions in its processing provenance, with no leftover raw
record exclusions in the derived-input split manifest.

#9's simple and tree baselines preserve already-derived values and use native
`observed_count` for their sample-count policy. They do not re-average hourly means
with raw rows. Saved model source receipts also bind this feature adapter and
shared causality/serialization helpers; prior artifacts require their prior code.

## Nested participant folds

`nested_participant_folds` builds deterministic, balanced grouped folds from
participant IDs and explicit config/exclusions, without reading values or labels.
Each eligible participant is held out in exactly one outer fold. Within each
outer development cohort, every participant validates once across inner folds.
Record exclusions travel with each split; whole-participant exclusions never
enter any partition. Empty groups or a declared minimum training cohort violation
are refused instead of silently reducing fold counts.

```python
from hachi.evaluation import NestedFoldConfig, nested_participant_folds

plan = nested_participant_folds(
    participant_roster,
    NestedFoldConfig(
        outer_folds=prespecified_outer_folds,
        inner_folds=prespecified_inner_folds,
        min_train_subjects=prespecified_minimum_training_cohort,
        seed=prespecified_seed,
    ),
    exclusions=canonical_exclusions,
)
for fold in plan.folds:
    # Canonical SplitManifest(..., fold=fold.outer_fold,
    #     n_folds=plan.config.outer_folds, **fold.partitions())
    # Use a manifest_id identifying BOTH outer and inner index.
    # Fit preprocessing and model on train; select on validation; test stays sealed.
    ...

# Only after inner-only model/parameter selection is frozen for this outer fold:
refit_partitions = plan.outer_partitions(outer_index)
# Refit on all outer development participants. The same outer test remains held out.
# Explicitly open a distinct test SplitManifest after recording selection/config hashes.
```

Persist the full nested plan privately and bind its `document_sha256` beside all
canonical split/run hashes. The canonical fold field identifies the outer fold;
inner indices live in the plan and distinct manifest IDs. Helpers never open test,
choose models or assert that scientific selection occurred. Do not select global
parameters from outer test performance. Combine outer-test predictions once per
participant for the final report; inner validation results are selection evidence.
Repeated episodes belonging to one participant follow that participant's partition;
event-task window/ongoing-episode handling still needs the clinical #8 protocol.
Fold counts and inclusion thresholds remain explicit scientific choices to freeze
against the admitted cohort, with sensitivity reports rather than automatic defaults.

## Reproduce the software path

From this worktree with its isolated environment:

```sh
uv sync --locked
uv run pytest tests/evaluation
uv run python -m hachi.evaluation.demo --output runs/issue-7-synthetic-001
```

The walkthrough generates six synthetic participants, keeps two each in
train/validation/test, and leaves test sealed. A last-known-value callback
illustrates the model hook. It does not implement #9's full baseline suite.

`write_packet` persists canonical split/run manifests, the cutoff plan, config,
evaluation results, source-file hashes, and a SHA-256 index. The supplied run
must match the split, config, snapshot, task, and result. A packet requires a new
directory and never overwrites a prior run. New directories/files use private
0700/0600 creation modes. Store packets under approved private storage: they
contain participant IDs and predictions. The demo uses ignored `runs/`; do not
commit real packets. A dirty-code run records `git_dirty` and the actual evaluator
source hashes; its base commit alone is not its full code identity.

## Paired comparisons

`compare_forecasts` fits both factories on the same training prefix and evaluates
the same participants, cutoffs and target grid. Pass separate baseline/candidate
configs: metric, aggregation, data mode, history policy and bootstrap settings
must match. Pretrained-overlap disclosures may differ by model. Comparisons with
different personal-history policies require a separate, explicit ablation design.

```python
from hachi.evaluation import compare_forecasts, write_comparison_packet

comparison = compare_forecasts(
    split_manifest,
    observations,
    targets,
    baseline_factory,
    candidate_factory,
    baseline_config=baseline_config,
    candidate_config=candidate_config,
)
write_comparison_packet(
    private_output,
    split_manifest,
    baseline_run,
    candidate_run,
    comparison,
)
```

Errors are paired by participant, cutoff and exact target bin. Both paired metric
reports use only labeled targets predicted by **both** models. The difference is
**candidate minus baseline**: negative MAE/RMSE/pinball differences favor the
candidate. Bootstrap resamples whole participant differences together, preserving
model correlation. Interval differences additionally require intervals from both
models on each paired target; narrower intervals alone do not establish quality.
No common targets gives unestimable metrics; a single paired participant has no
between-participant CI.

The summary keeps baseline-only, candidate-only, both-abstained, missing-label,
and insufficient-history counts beside the paired count. These categories
reconcile to the expected retained target bins. Both full evaluation reports are
retained separately. Paired error is conditional on shared prediction coverage:
a selectively abstaining candidate cannot be promoted from that number alone.
There is no automatic winner, accuracy threshold, or model-promotion decision.

The private comparison packet contains `comparison.json` and complete
`baseline/` and `candidate/` packets, each with its canonical run manifest, model
reference, config, split, predictions and hashes. Summary hashes bind the exact
two evaluated results; both runs must have distinct run IDs and correct manifest
and config identities before any output directory is created.

```sh
uv run python -m hachi.evaluation.demo --paired --output runs/my-paired-demo
```

This compares last-known-value and two-sample linear-prefix **synthetic callback
examples**, not validated physiological models or the full #9 baseline suite.

## Remaining integration gates

- #5's admitted, reproducible PMData snapshot and availability-preserving adapter;
  representative source-to-feature reconciliation and a nonempty real cohort.
- Cohort-appropriate use of the nested grouped-fold helper and scientific split/count,
  coverage, lookback, embargo, and bootstrap sensitivity choices frozen before
  test opening. This implementation supports one explicit fold at a time.
- The agreed real baseline report with code/data/split hashes. Current checks
  establish causal software behavior only.
- Outcome-specific episode grouping, illness/anomaly/recovery metrics, and
  supervised/stacking safeguards after their inputs/protocols are defined. This
  hourly physiology slice does not complete those parts of #7 or later issues.
- Apply the paired comparison to actual models and measure operational costs;
  paired error alone is not a model-selection gate or real-data evidence.

## #5 to #7 handoff requirements

The first real run needs the following from the data owner; no new shared schema
or speculative PMData-specific parser is needed before that interface is agreed.

1. An admitted PMData version, approved private snapshot location, reproducible
   processing command, and canonical `DatasetSnapshotRef`. Confirm source and
   feature hashes and aggregate counts; do not send raw participant records or
   predictions through the agent inbox.
2. The participant roster and explicit subject/record exclusions. Keep identifiers
   and the persisted split in approved private storage. The synthetic six-person
   split and October 2026 dates are demonstration settings, not PMData settings.
3. Canonical `Observation` rows or readiness-bearing `HourlyFeature` inputs, preserving metric/unit, event
   interval and `available_at_utc`. Where historical availability is not observed,
   provide the documented `availability_rule` and mark availability `assumed`.
   A complete aggregate table cannot safely substitute for these feature inputs:
   canonical `Aggregate` has no availability timestamp. If #5 exposes only
   aggregates, use the agreed `FeatureBin` view and the explicit inclusion policy
   above. Never invent availability from the final aggregate alone.
4. Canonical hourly `Aggregate` labels for one agreed level metric/aggregation,
   with explicit missing bins, source exclusions and the pipeline version.
   Duplicate-source precedence and quarantined source contributions must already
   be resolved upstream. If the first usable task is daily-only, the current
   hourly slice needs an agreed extension rather than silently changing its target.
5. Aggregate coverage and participant/day/bin counts, timezone/UTC grid semantics,
   and the usable historical date range. These determine real lookback, horizon,
   inclusion and fold choices; those choices remain pending cohort inspection.

The evaluator consumes parsed canonical model instances. Storage transport
(for example Parquet versus JSONL), approved access and reader ownership should
be agreed with #5. Loading and verifying that snapshot is an integration step;
the local synthetic packets establish none of its data-admission requirements.

Once available: reconcile representative source records, define the real split
and inclusion protocol, keep test sealed, run validation and a real baseline,
then verify packet hashes and denominators against #5's audit. Scientific fold
selection, full leakage/outcome coverage remain issue
gates; a successful synthetic run does not close #7.

No data acquisition, service, GPU job, publication, or GitHub state change is
performed by this package.

## Local verification

Verified on the isolated `issue-7-ezzy-integration` worktree based on main
`1637e748078ed0c49029b9cc4b78776430ef3c22`, including the merged Apple importer.
Python 3.12.13, Pydantic 2.14.0, pytest 9.1.1, Ruff 0.17.0. The focused suite has
34 tests; the integrated full suite has 233 tests, plus 5 coordination tests. Repository lint,
formatting, generated schema/fixture staleness, generated TypeScript staleness,
and TypeScript compilation pass.

The host's Bun 1.3.13 cannot read the existing version-2 lockfile. Repository setup
and checks passed using a temporary Bun 1.4.0 installation, with no lock edits or
global tool upgrade:

```sh
npm exec --yes --package=bun@1.4.0 -- make setup
npm exec --yes --package=bun@1.4.0 -- make check
```

Fresh integrated single-model and paired walkthroughs use six generated participants,
two validation participants, four retained rolling origins and eight target bins.
The paired run scores all eight bins jointly. These are software-check counts only,
with test participants sealed. Packet and evaluator-source hashes and private
0700/0600 storage modes are independently checked. Only the sanitized aggregate
receipt is committed; predictions and split identifiers stay in ignored `runs/`.

### Hourly adapter checkpoint

On clean code commit `4cd9da72073e554b5ccb7ece3cf401630f3aaa9d`, the full suite
passes 272 Python tests plus 5 coordination tests. All lint and generated schema,
fixture, TypeScript staleness and compilation gates pass. The 70 focused
evaluation/model/causality tests include derived/raw tree-fit parity, data-only
artifact readback, future-readiness sentinels and explicit exclusion handling.
A fresh generated-only four-model demo verifies saved-artifact prediction/count
replay and all packet hashes/private modes under ignored
`runs/issue-7-hourly-adapter-001`. The sanitized aggregate receipt is
[`evidence/hourly-feature-adapter.json`](evidence/hourly-feature-adapter.json).
It distinguishes the raw generated demo from derived-input tests and establishes
no real-cohort accuracy or integration claim.
