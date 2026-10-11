# Issue #7 — CPU evaluation groundwork

This implements the data-independent portion of #7, continued from NobleBadger's existing work without modifying its original checkout. The real-cohort
acceptance gate remains **blocked on #5 PMData**. Synthetic results demonstrate
software behavior, not forecast accuracy or real-data integration.

## Caller and boundaries

Use the merged canonical `Observation`, `Aggregate`, `SplitManifest`, and
`RunManifest` models. No shared schema, dependency, or root lockfile is changed.
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
  Aggregates lack availability timestamps, so they are deliberately **labels
  only**. A PMData feature adapter must preserve raw/derived feature availability;
  simply feeding the full precomputed aggregate table into a model is unsafe.
- Counts reconcile expected retained target bins to scored, missing-label,
  labeled abstention, or insufficient-history points. Scheduler purges are
  reported separately by origin. A missing label never becomes zero or healthy.
- MAE, RMSE, and median (0.5) pinball loss are computed per participant, then
  averaged with equal participant weight. Bootstrap draws resample participants;
  a single participant has no estimable between-participant CI. Interval coverage
  and width are conditional on scored points with supplied intervals. No nominal
  interval coverage or calibrated accuracy claim is invented.

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
- Cohort-appropriate grouped/nested cross-validation and scientific split/count,
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
3. Canonical `Observation` rows for model inputs, preserving metric/unit, event
   interval and `available_at_utc`. Where historical availability is not observed,
   provide the documented `availability_rule` and mark availability `assumed`.
   A complete aggregate table cannot safely substitute for these feature inputs:
   canonical `Aggregate` has no availability timestamp. If #5 exposes only
   aggregates, agree an availability-preserving view with the contracts owner
   before wiring it into this evaluator.
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
selection, full leakage/outcome coverage and teammate reproduction remain issue
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
