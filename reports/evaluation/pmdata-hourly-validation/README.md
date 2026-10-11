# Real PMData hourly HR validation

This is actual permitted PMData, not fixture accuracy. The selected outer fold has
12 unique development-validation participants and four **sealed** test participants.
Each of three inner folds trains on eight, validates on four and reserves the same
outer test. Whole-person grouping keeps every episode of a person in one partition.
There are no participant intersections or explicit exclusions. Source admission,
clock and availability assumptions remain those in the #5 snapshot report.

Primary execution: clean `bca82fdd2a15d42c5da14ce5c9d897a4f7c58a37`, Python 3.12.13,
locked environment SHA `2fa7fc3ccb8453e5403a2aebe00ef7b8176f2a281e2ffd3546928b892a65f8bc`.
The source archive and all table/audit content reproduced the published snapshot
`06606ac2708b1c5329b1cfa04e6edfb9a0583c5a6c9f2eb1465b07aebab2ee47` locally.
A separate raw-archive path reconciled 2,400 sampled values across 15 checks with
zero mismatches. See [acceptance.json](acceptance.json).

## Frozen primary protocol

[Configuration](../../../configs/evaluation/pmdata-hourly-validation.json):
HR mean, native coverage at least 0.5 and count at least 30 for features and labels;
48-hour causal personal prefix, at least 24 eligible hourly bins; next 24 whole UTC
hours, daily origins, zero embargo, January 1–8 2020 UTC. Parameters and dates were
committed before observing primary metrics. Split timestamps are fixed for matching
hashes. Native CPU models have no pretrained overlap; personal history is explicitly
permitted for a new held-out person. This does not establish Apple Watch transfer.

The complete source has 46,406 included HR mean feature bins; other aggregates and
missing HR bins remain separately counted. Across the validation grid: 2,016 expected
targets, 168 insufficient-history points and 249 missing labels. The remaining 1,599
labeled eligible targets are the coverage denominator. Counts repeating roster or
training cohorts across folds must not be interpreted as unique participants.

| Model | MAE bpm (95% participant CI) | RMSE bpm | Scored / eligible labeled | Labeled abstentions |
|---|---:|---:|---:|---:|
| Last valid | 12.03 (10.94–13.01) | 17.21 | 1,599 / 1,599 | 0 |
| Seasonal naive | 11.15 (9.42–12.94) | 17.11 | 1,464 / 1,599 | 135 |
| Train population mean | 12.20 (10.27–14.19) | 16.14 | 1,599 / 1,599 | 0 |
| Frozen tree | 10.32 (9.38–11.30) | 14.39 | 1,481 / 1,599 | 118 |

Metrics average participant errors equally, with 1,000 participant bootstrap draws
and 95% intervals. All twelve fitted artifacts passed saved-model prediction/count
replay. No model supplies forecast intervals; interval coverage and width are
unestimable. Point forecasts do not imply calibrated uncertainty.

## Paired evidence and sensitivity

Tree minus last-valid paired MAE is −1.80 bpm (95% CI −3.14 to −0.46), on 1,481
common targets. Tree minus population mean is −1.53 (−2.98 to +0.12); tree minus
seasonal is −0.81 (−2.36 to +0.67), on 1,387 common targets. The latter MAE intervals
include zero. All paired baseline/candidate results matched the original frozen
results by hash. [paired.json](paired.json) retains exclusive predictions, joint
abstentions and missingness. Coverage differs; **no final winner is selected**.

Two exploratory inner-validation sensitivities were frozen after primary results
and before their execution; they do not open test or replace the primary protocol.
Shorter history changes both lookback to 24 hours and minimum eligible history to
12 bins. Tree MAE is 10.29, last-valid 11.93, seasonal 11.09 and population mean
12.00; coverage is separately reported in [lookback24.json](lookback24.json).
A 24-hour embargo predicts hours 24–47 after origin (tree lead support extended to
47), with fewer complete target origins. MAEs are 10.59, 13.24, 10.66 and 12.27
respectively; see [embargo24.json](embargo24.json). These are conditional errors with
different denominators, not a paired improvement claim or final tuning decision.

Primary fit, evaluation and artifact replay took 41.62 s with process peak RSS
619,053,056 bytes on Ezzy's MacBook Air. Nine paired replays took 26.59 s /633,503,744
bytes. These are whole-process costs including verification/replay, not isolated
inference latency; full per-model timing is in [baseline.json](baseline.json).

## Real-input leakage sentinel

[real-input-sentinel.json](real-input-sentinel.json) records twelve actual fits/replays:
all four CPU models in all three inner folds. Changing future and sealed outer-test
HR feature values to 299 bpm left the causal fitted states and earlier first-day
predictions/counts identical. The altered values are a sentinel experiment, not
accuracy evidence. Source/record IDs of eligible earlier features remain stable.
Backdated availability, target-missingness, overlapping horizons and frozen-training
behavior also have focused generated regression tests in tests/evaluation and
tests/models. Historical source availability remains assumed, not observed.

## Reproduce and locate outputs

```sh
uv run --extra baselines python -I -m hachi.evaluation.pmdata_run \
  --snapshot /approved/private/derived/pmdata-features-1-simula-2020-04-24-06606ac2708b \
  --protocol configs/evaluation/pmdata-hourly-validation.json \
  --output /approved/private/runs/pmdata-validation-new
uv run --extra baselines python scripts/evaluation/pmdata_paired.py \
  --snapshot /approved/private/derived/pmdata-features-1-simula-2020-04-24-06606ac2708b \
  --protocol configs/evaluation/pmdata-hourly-validation.json \
  --baseline-run /approved/private/runs/pmdata-validation-new \
  --output /approved/private/runs/pmdata-paired-new
```

Baseline packets are privately stored under
`/Users/ezzyrappeport/hachi/runs/pmdata-hr-validation-20261011-001/`; paired packets
use `pmdata-hr-paired-20261011-001/`. Per-fold models live in `models/<artifact_id>`;
canonical split/run/evaluation packets in `evaluations/<model_id>`. They contain
participant IDs/predictions and are not committed. [packet-index.json](packet-index.json)
publishes only split/origin/evaluation hashes; [baseline.json](baseline.json) publishes
artifact references. All packet indexes and 0700/0600 modes were checked locally.
Run timestamps differ between reproductions; evaluation and deterministic split
content can match exactly. Baseline implementation/source receipts must match.

PMData illness status is unknown. Healthy alert burden is **unestimable** here and
remains #9's separate clinical gate. This report supplies #7's real physiology
harness evidence, while event-specific clinical protocols and final selection/test
opening remain later task work. No clinical diagnosis, prospective accuracy,
calibrated intervals or final product-model promotion is claimed.
