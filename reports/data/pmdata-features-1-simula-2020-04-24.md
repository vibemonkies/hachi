# PMData feature snapshot `pmdata-features-1-simula-2020-04-24-06606ac2708b`

Cohort-level audit of the first canonical PMData snapshot (#5). It holds aggregate counts only, with no participant ids or rows. The full machine-readable report is [`pmdata-features-1-simula-2020-04-24.json`](pmdata-features-1-simula-2020-04-24.json). The snapshot itself and its private per-participant audit stay in approved storage.

## Identity

| | |
|---|---|
| `DatasetSnapshotRef` | `pmdata` / `simula-2020-04-24` / `06606ac2708b1c5329b1cfa04e6edfb9a0583c5a6c9f2eb1465b07aebab2ee47` |
| Source archive | `pmdata.zip`, 1,416,129,266 bytes, sha256 `53a49d94a2e9713fb8a0fc57d4d9dec3e1e4d2ae866969cd1f7537a5bc125357` (registry entry `configs/datasets/pmdata.toml`); 267 members read and hashed |
| Pipeline | `pmdata-features-1`, config `configs/features/pmdata.toml` sha256 `c0d0d6e34401c401bf86d677c36e491ee221d0277b941c83c8ac7a4b54e5d4e8` |
| Built from | commit `a7ed306778a1b2d2c85e7017078fc70782ef385e` (clean tree), Python 3.12.13, pyarrow 26.0.0, pydantic 2.14.0 |
| Command | `HACHI_DATA_ROOT=/Volumes/T7/Stockpile/hachi.datasets uv run python -I -m hachi.data.pmdata build --report reports/data/pmdata-features-1-simula-2020-04-24.json` (1,233 s, 1.4 GB peak RSS) |
| Locations | Mac: `$HACHI_DATA_ROOT/derived/<snapshot-id>/`; GX10: `~/hachi/data/derived/<snapshot-id>/` (read-only, `sha256sum -c SHA256SUMS` passes) |

| Table | Rows | sha256 |
|---|---:|---|
| `observations.parquet` | 24,182,736 | `d0b76421f43da2b543d07b62efc121bbd99d2cf05bf0a71a153a1f40b3bc3f5a` |
| `aggregates_hourly.parquet` | 604,989 | `b0c58d73ce8a2c08c7c55152cc4f47222514faf0d37b87cf25509cd91eb471aa` |
| `aggregates_daily.parquet` | 27,660 | `3f51b0cf5d900b3f7c8c1ebb51dc9de3d3f8f2f96337bd7bd65bf54a157fd594` |
| `wellness_daily.parquet` | 16,226 | `b08788e15dfc12a709f8950dee8161ae90518312adeefb6cb37baa336e44cb90` |
| `outcomes.parquet` | 16 | `c8bda057b9701fbf4c5fbb2e335f75e12b3251a4faa954e46de50de21c42edd6` |

## Verification

- **Deterministic reprocessing.** A second, independent build from the same commit gave the same snapshot id and a byte-identical `SHA256SUMS`, covering all seven files including the manifest and audit.
- **`verify --full --archive`** passed:
  - every file matches its checksum and the manifest;
  - all 267 archive members read match their recorded hashes;
  - every row of every table re-validates against the canonical contracts;
  - record ids and bins are unique.
- **`reconcile`** recomputed 2,400 sampled values straight from the raw archive by a separate code path, with **0 mismatches**. It covered 4 participants and 15 checks: hourly/daily steps sum and count, heart-rate mean and max, vendor resting HR, deep sleep, awake time and time in bed.
- **Row accounting.** Every member's parsed row count equals the entry count published in the PMData paper (Figure 3) for all 17 counted members. For each ingested Fitbit member, every parsed row lands in exactly one disposition.

## Cohort

16 participants. Per participant (min / median / max):

| | min | median | max |
|---|---:|---:|---:|
| Local days in span | 114 | 147 | 153 |
| Days with heart rate (daily mean valued) | 62 | 138 | 151 |
| Days with steps | 83 | 144.5 | 153 |
| Days with vendor resting HR | 0 | 119.5 | 152 |
| Days with time in bed | 9 | 135.5 | 151 |
| Sleep logs kept | 8 | 137.5 | 181 |
| Days with a wellness report | 67 | 102.5 | 147 |

Two participants have no resting-HR file. No whole participant is excluded by #5; inclusion is a #7 protocol decision.

## Sources, duplicates and exclusions

| Member | Parsed | Accepted | Duplicates dropped (identical / conflicting) | Other |
|---|---:|---:|---:|---|
| `heart_rate.json` | 20,991,392 | 20,985,494 | 5,898 / 0 | confidence 0/1/2/3: 257,376 / 5,804,591 / 8,300,786 / 6,628,639 (all kept) |
| `steps.json` | 1,534,705 | 1,534,012 | 559 / 134 | 953,071 recorded zeros; absent minutes stay absent |
| `distance.json` | 1,534,705 | 1,534,012 | 559 / 134 | centimetres → metres |
| `resting_heart_rate.json` | 1,803 | 1,658 | 0 / 0 | 145 "no estimate" rows (`date: null, value: 0`) |
| `sleep.json` (logs) | 2,064 | 1,993 | 63 / 0 | 8 quarantined across DST; 0 overlapping; 519 classic "restless" segments excluded |
| `pmsys/wellness.csv` | 1,747 | | 23 same-day reports superseded | out of scale: fatigue 2, mood 3, sleep quality 2, soreness 2, stress 3 |

Excluded members are parsed and counted but not ingested:

| Member | Rows | Reason |
|---|---:|---|
| `calories.json` | 3,377,529 | Total energy expenditure, including basal; not `active_energy` |
| Activity-level minutes (four files) | 9,432 | No canonical metric |
| `time_in_heart_rate_zones.json` | 2,178 | No canonical metric |
| `exercise.json` | 2,440 | No canonical metric |
| `sleep_score.csv` | 1,836 | No canonical metric |
| `srpe.csv` | 783 | Not in this snapshot |
| `injury.csv` | 225 | Not in this snapshot |
| Google Forms `reporting.csv` | 1,569 | Not in this snapshot |
| Food images | 643 files | Never opened |
| `participant-overview.xlsx` | | Never opened |

Stage totals reconcile with Fitbit's own per-log summary within 60 s for 1,902 of 1,993 kept logs. Staged logs that miss do so by about 2–3 min: Fitbit counts slightly more wake than its listed short wakes. A few classic logs miss by more, in restless/awake accounting. Observations follow the per-segment data.

## Missingness

Empty bins are explicit (`no_observations`), never zero.

| Resolution | Metric | Bins | With value | No observations | Insufficient coverage | Mean coverage of valued bins |
|---|---|---:|---:|---:|---:|---:|
| hour | heart_rate (mean) | 54,999 | 46,406 | 7,327 | 1,266 | 0.975 |
| hour | steps | 54,999 | 46,593 | 8,406 | 0 | 0.549 |
| hour | sleep_in_bed | 54,999 | 16,722 | 38,277 | 0 | 0.881 |
| day | heart_rate (mean) | 2,305 | 2,022 | 119 | 164 | 0.914 |
| day | steps | 2,305 | 2,185 | 120 | 0 | 0.488 |
| day | resting_heart_rate_vendor | 2,305 | 1,658 | 647 | 0 | 1.000 |
| day | sleep_in_bed | 2,305 | 1,926 | 379 | 0 | 0.319 |
| day | sleep_asleep_deep | 2,305 | 1,885 | 420 | 0 | 0.322 |

Steps coverage is about 0.5 even on worn days, because the export omits many minutes that heart rate shows were worn. Absent minutes are unknown, so step sums are sums of recorded minutes. The other metrics are in the JSON report.

## Wellness labels and scale direction

Each wellness item has 2,318 participant-days: 1,724 with a report and 594 `no_survey`. No-survey days are unknown, never healthy. PMData has no illness labels, so each participant has one `StatusUnknown` outcome. Fatigue is never used as illness.

**Fatigue: higher means less fatigued** (1 Very tired, 2 More tired than normal, 3 Normal, 4 Fresh, 5 Very fresh), per the PMSys screenshots in the PMData paper, Figure 2. The data agrees: the participant-centred correlation with readiness (0 Not Ready … 10 Max Ready) is +0.513 over 1,722 days. Mood (+0.256), soreness (+0.269) and stress (+0.152) are also documented as higher-is-better. Sleep quality's labels are not shown in the paper. Its direction is recorded as undocumented despite its +0.256 correlation.

## Time mappings

- **Fitbit intraday timestamps are UTC; sleep logs are Oslo wall time.** Over 786,999 asleep main-sleep minutes, mean heart rate is lowest at probe shift 0 of that joint mapping (58.12 bpm, against 59.88 at −60 min and 59.50 at +60 min). Steps per asleep minute are also lowest there (3.11, against 5.59 and 7.61).
- **The participant-week view mostly agrees.** Of 311 participant-weeks with enough data, 287 have their minimum at shift 0. The other 24 may reflect travel or noise; they are reported, not corrected.
- **PMSys `Z` timestamps are true UTC.** Read as UTC, 69 of 1,747 reports fall inside a main sleep. Read as local time, 603 do.
