# PMData canonical features (#5)

This turns the admitted PMData archive (`configs/datasets/pmdata.toml`, version `simula-2020-04-24`) into an immutable feature snapshot of canonical tables. The archive is checksum-pinned, streamed and never extracted. Snapshots live outside Git, at `$HACHI_DATA_ROOT/derived/<snapshot-id>/` and read-only on the GX10 at `~/hachi/data/derived/<snapshot-id>/`. Only the sanitized cohort report goes in Git: [`reports/data/`](../../../../reports/data/).

## Commands

```sh
export HACHI_DATA_ROOT=/Volumes/T7/Stockpile/hachi.datasets   # holds pmdata/pmdata.zip
uv run python -I -m hachi.data.pmdata build --report reports/data/pmdata-features-1-simula-2020-04-24.json
uv run python -I -m hachi.data.pmdata verify  "$HACHI_DATA_ROOT/derived/<snapshot-id>" --full --archive "$HACHI_DATA_ROOT/pmdata/pmdata.zip"
uv run python -I -m hachi.data.pmdata reconcile "$HACHI_DATA_ROOT/derived/<snapshot-id>"
```

`build` refuses an archive whose name, size or SHA-256 differs from the registry, and it never overwrites a snapshot. It builds in a private staging directory and leaves nothing behind on failure. On success it renames the directory to `<pipeline_version>-<dataset_version>-<first 12 hex of the snapshot hash>` and makes it read-only. The snapshot hash covers the archive, every member read, the pipeline config, every table and the audit. It deliberately leaves out how the build ran (git SHA, library versions); the manifest records those under `built_with`. The same code, config and archive therefore give a byte-identical directory.

`verify` checks `SHA256SUMS`, the manifest identity and the table row counts. `--full` re-validates every row against the contracts and checks record-id and bin uniqueness. `--archive` re-hashes every archive member that was read. `reconcile` recomputes sampled hourly and daily values straight from the raw archive by a separate route: whole-file `json`, plain `datetime`/`zoneinfo`, and sleep painted on 30 s ticks instead of carved intervals.

## Reading a snapshot

```python
from hachi.data.pmdata import (
    dataset_snapshot_ref,
    iter_aggregates,
    iter_observations,
    read_wellness,
)

ref = dataset_snapshot_ref(snapshot)  # DatasetSnapshotRef for run/split manifests
for obs in iter_observations(snapshot, as_of=cutoff, subjects=["p01"], metrics=["steps"]):
    ...  # canonical Observation; only records ended and available by the cutoff
for aggregate, available_at in iter_aggregates(
    snapshot, "hour", as_of=cutoff, metrics=["heart_rate"]
):
    ...  # canonical Aggregate, only bins ended and final by the cutoff
```

Heart rate holds about 21 million rows. Filter by subject, metric and time window; `pyarrow` pushes the filters down to row groups.

## Tables

| File | Rows are | Notes |
|---|---|---|
| `observations.parquet` | canonical `Observation` | Exactly the contract columns, sorted by subject, metric, start, record id |
| `aggregates_hourly.parquet`, `aggregates_daily.parquet` | canonical `Aggregate` plus `available_at_utc` | Every bin of each participant's span, for every metric |
| `wellness_daily.parquet` | PMData `WellnessDay` (this module) | Every local day × item; a day without a report is `no_survey` |
| `outcomes.parquet` | canonical `StatusUnknown` | One per participant: PMData has no illness labels |
| `manifest.json`, `audit.json`, `SHA256SUMS` | | Roster, hashes, mappings, private per-participant audit |

## Sources and mappings

| Member | Becomes | Rule |
|---|---|---|
| `fitbit/heart_rate.json` (≈5 s samples) | `heart_rate` points, bpm | Instants; contract bounds 1–300 |
| `fitbit/steps.json` (per minute) | `steps`, count | A recorded 0 is a 0; an absent minute stays absent |
| `fitbit/distance.json` (per minute, cm) | `walking_running_distance`, m | ÷100 (the paper documents centimetres); same minutes as steps |
| `fitbit/resting_heart_rate.json` (daily) | `resting_heart_rate_vendor`, bpm | Local day only, never hourly; `{date: null, value: 0}` means no estimate |
| `fitbit/sleep.json` | `sleep_in_bed`, stage durations | Stages: light→`core`, deep, rem, wake→`awake`; classic: asleep→`unspecified`, awake; restless and unknown excluded |
| `pmsys/wellness.csv` | wellness outcomes | Latest report of a local day wins; out-of-scale values are null |

Excluded members are still parsed so their row counts reconcile. Calories are total energy expenditure including basal, which is not `active_energy`. Activity-level and HR-zone minutes, exercise logs, sleep scores, sRPE, injuries and Google Forms reports have no canonical metric, so they are not ingested. Food images and `participant-overview.xlsx` are never opened. The audit lists each member with its reason and its parsed count against the paper's Figure 3.

**Clocks.** The paper states no timezone. The cohort is Norwegian and the data agrees: Fitbit intraday series (heart rate, steps, distance) are UTC without an offset, and sleep logs are Oslo wall time. Every build re-measures this. Steps and heart rate inside asleep minutes are lowest at shift 0 of the joint mapping (`clock_alignment` in the audit; intraday data on local time would put the minimum at +60 min). PMSys `Z` timestamps are real UTC: read as UTC, few reports fall inside a main sleep, and read as local time, many more do (`wellness_timing`). Observations carry `tz_name: Europe/Oslo` with `tz_provenance: dataset_documentation`. That documentation is this module's mapping and its measured evidence, not a timezone stated by the dataset. The provenance enum has no "inferred" value, and adding one would be a shared contract change.

**Availability.** Fitbit's export has no sync or creation time, so every observation is `assumed` with a named rule. Intraday records become available at their end, vendor resting HR at the end of its local day, and every sleep segment at the end of its whole sleep log. Lags are configurable and default to 0. A deep-sleep segment that ended at 02:00 is therefore not usable at 03:00 if the log ended at 07:00.

**Sleep.** Duplicated log ids are identical apart from Fitbit's rolling thirty-day averages, so each is kept once. A duplicate that differed in anything else would be dropped. Logs spanning a DST change are quarantined, because their local times cannot be placed unambiguously. Overlapping distinct logs would be quarantined too; the real archive has none. Fitbit's `shortData` short wakes are carved out of the long stage segments. With them, stage totals reconcile with Fitbit's own per-log summary for most logs; the audit counts the rest.

**Duplicates.** Exact duplicates are kept once. Conflicting duplicates (same instant, different values) are all dropped.

## Aggregates and train-time semantics

- Hour bins are UTC hours. Day bins run from local midnight to midnight in Europe/Oslo, so the DST day is 23 h.
- Levels (heart rate) take mean, min and max. Amounts and durations are summed. Sleep durations crossing a bin edge are split by exact overlap. Vendor resting HR is binned only by day.
- An empty bin is `value: null`, `null_reason: no_observations`, `coverage: 0`, never zero.
- Coverage is the fraction of the bin with usable data. For heart rate that is minutes with samples; for steps, distance and resting HR, the observations' own intervals; for sleep states, time inside any kept sleep log.
- Heart-rate bins below 0.5 coverage are null with `insufficient_coverage`. Other metrics keep any covered value. Their `coverage` column carries the mask (`configs/features/pmdata.toml`).
- `available_at_utc` is `max(bin end, availability of every observation and coverage span the bin depends on)` (rule id `pmdata-aggregate-final-at-latest-input`, exported as `AGGREGATE_AVAILABILITY_RULE`). For every cutoff at or after it, the stored row equals the bin recomputed from `iter_observations(as_of=cutoff)`; a synthetic property test checks this. Before it, recompute from observations, because the stored value may use later data. Never feed the whole table to a model without this filter.
- Day bins split a night at local midnight. Use observations for per-night totals.

## Wellness

| Item | Scale | Higher means | Evidence |
|---|---|---|---|
| fatigue | 1–5 | **less fatigued** | PMSys labels: 1 Very tired, 2 More tired than normal, 3 Normal, 4 Fresh, 5 Very fresh |
| mood | 1–5 | better mood | 1 Very bad mood … 5 Very good mood |
| readiness | 0–10 | more ready to train | 0 Not Ready … 10 Max Ready |
| soreness | 1–5 | less sore | 1 Very sore … 5 Great |
| stress | 1–5 | less stressed | 1 Highly stressed … 5 Very relaxed |
| sleep_quality | 1–5 | undocumented | The paper says only that 3 is normal |
| sleep_duration_h | 0–12 h | longer reported sleep | App choices |

The labels come from the PMSys screenshots in the paper (Thambawita et al., MMSys 2020, Figure 2). The audit also reports each item's participant-centred correlation with readiness. Fatigue is a wellness rating, never an illness label. A missing report is unknown, never healthy. `soreness_area` (body-area codes) is excluded.

## Verification

Synthetic tests (`tests/data/pmdata/`) cover: a generated archive in PMData's layout, crossing the Oslo DST change; duplicate, conflicting and out-of-bounds records; DST-spanning, overlapping and duplicated sleep logs; short-wake overlays; the resting-HR sentinel; sparse steps; out-of-scale and same-day wellness; archive refusal; contract validity; byte-identical rebuilds; tamper detection; as-of recomputation; and raw-archive reconciliation.

The first real snapshot is `pmdata-features-1-simula-2020-04-24-06606ac2708b`, built from commit `a7ed306`. A second build was byte-identical; `verify --full --archive` and `reconcile` (2,400 values, 0 mismatches) pass; and all 17 counted members match the paper's entry counts. Its sanitized cohort audit is [`reports/data/pmdata-features-1-simula-2020-04-24.md`](../../../../reports/data/pmdata-features-1-simula-2020-04-24.md).
