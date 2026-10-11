# Illness and recovery outcome labels (#8)

This turns admitted illness cohorts into immutable label snapshots: canonical `SymptomEpisode`, `TestResult` and `StatusUnknown` rows, plus the onset-window and recovery tables #13 (onset) and #14 (recovery) train and evaluate on. The definitions are locked in [`configs/outcomes/definitions.toml`](../../../../configs/outcomes/definitions.toml). Each dataset's mapping sits beside it in one TOML per dataset. Source files are checksum-pinned by the dataset registry (`configs/datasets/`). Snapshots live outside Git, at `$HACHI_DATA_ROOT/derived/<snapshot-id>/` and read-only on the GX10 at `~/hachi/data/derived/<snapshot-id>/`. Only the sanitized aggregate reports go in Git: [`reports/data/clinical-*`](../../../../reports/data/).

| Dataset | Labels from | Status |
|---|---|---|
| `stanford-covid19-wearables` (Mishra 2020) | Supplementary Data 1: Table 3 (category, onset, diagnosis and recovery dates) and Table 5 (daily symptom surveys) | Built |
| `stanford-covid19-wearables-phase2` (Alavi 2022) | Source data: each COVID-19 positive's test date, symptom onset or none, recruitment and device | Built |
| `cmu-common-cold-project` | Five-study file: daily baseline-adjusted Jackson scores, "have a cold?", viral shedding, infection | Adapter tested on synthetic rows only; gated on CMU analysis registration |
| CovIdentify, Homekit2020, Evidation ILI | | Access blocked (see the report) |

## Commands

```sh
export HACHI_DATA_ROOT=/Volumes/T7/Stockpile/hachi.datasets
uv run python -I -m hachi.data.clinical build stanford-covid19-wearables --report-dir reports/data
uv run python -I -m hachi.data.clinical build stanford-covid19-wearables-phase2 --report-dir reports/data
uv run python -I -m hachi.data.clinical verify "$HACHI_DATA_ROOT/derived/<snapshot-id>" --full
```

`build` refuses any source file whose name, size or SHA-256 differs from the registry. It builds in a private staging directory, leaves nothing behind on failure, and never overwrites a snapshot. The directory is named `<pipeline_version>-<dataset_id>-<dataset_version>-<first 12 hex of the snapshot hash>` and is made read-only. The hash covers the source files, both configs, every table and the audit. It leaves out how the build ran (git SHA and library versions are recorded under `built_with`), so the same code, configs and sources give a byte-identical directory. Phase 2 streams 36 GB of CSV from its zip, which takes a few minutes. Archives are never extracted.

The CMU build exits before reading anything unless `[analysis_registration]` in `configs/outcomes/cmu-common-cold-project.toml` records the submitted Data Analysis Form, as CMU's agreement requires.

## Reading a snapshot

```python
from hachi.data.clinical import dataset_snapshot_ref, labels_known_by, read_outcomes, read_table

ref = dataset_snapshot_ref(snapshot)  # DatasetSnapshotRef for run/split manifests
outcomes = read_outcomes(snapshot)  # validated contract rows
windows = read_table(snapshot, "onset_windows")  # pyarrow Table; filter subjects=[...]
recovery = read_table(snapshot, "recovery")
```

| Table | Rows are | Use |
|---|---|---|
| `subjects.parquet` | one per participant: span, follow-up start/end, whether in the label tables, undated illness, episode/test/survey/wearable-day counts, category, recruitment, device | Denominators; controls |
| `status_intervals.parquet` | run-length intervals tiling each span: `observed_symptom_free`, `observed_symptomatic`, `observed_intermediate` or `unknown`, with source, `available_at_utc` and `availability_rule` | Observed healthy time (for alert burden) vs unknown time |
| `outcomes.parquet` | canonical `SymptomEpisode` / `TestResult` / `StatusUnknown` (flattened; `read_outcomes` validates) | Episodes resolve on the canonical endpoint, `outcomes-1-sustained-symptom-free-2d` |
| `episodes.parquet` | one per episode: category, onset day range, merged relapse onsets, confidence, linked tests, recruitment, device, HR days in the 28 days before onset, last ongoing and washout days | Episode grouping key for splits (`episode_id`); filter COVID-19 vs other illness here |
| `onset_windows.parquet` | one per participant × cutoff at local midnight, with `onset_{24,48,72}h`, the episode behind a positive, and `test_{24,48,72}h` | #13's at-risk windows: train on `positive` vs `negative` only |
| `recovery.parquet` | one per episode × endpoint: status, reason, resolution day range, follow-up, day indices from onset | #14's event/censoring labels |
| `surveys.parquet` | completed survey day × state (`symptomatic`, `symptom_free`, `intermediate`) | Survey coverage, negatives |
| `wearable_days.parquet` | participant-day record counts for heart rate, steps and sleep | Which cutoffs have wearable history |
| `manifest.json`, `audit.json`, `SHA256SUMS` | | Identity, configs, sources, clock, availability rules, aggregate audit |

**Availability.** The sources record no entry times. A survey answer is assumed available at the end of the local day it describes (`survey-available-at-end-of-its-local-day`). Episode and test labels are assumed known only at the end of the participant's follow-up (`labels-known-at-end-of-participant-follow-up`, which is `observed_at_utc` in the contract rows), so `label_known_by` never leaks a label into an earlier cutoff.

## Definitions (`outcomes-1`)

**Onset.** A cutoff is local midnight, and a horizon of 24/48/72 h covers the next 1/2/3 local days. Labels per cutoff and horizon:

| Label | Meaning |
|---|---|
| `positive` | An episode's whole onset interval lies inside the window. |
| `negative` | No onset, and every day of the window has a completed survey reporting no symptoms. |
| `uncertain_partial_onset` | An onset interval straddles the window edge or the cutoff. |
| `uncertain_unexplained_symptoms` | No reported onset, but a survey in the window reports symptoms. |
| `unknown_no_survey` | No reported onset and incomplete survey coverage. Not a negative; use only in a declared sensitivity analysis. |
| `unknown_follow_up_ended` | The window runs past the participant's data. |
| `excluded_ongoing_episode` | An episode began before the cutoff and has not resolved. |
| `excluded_washout` | Within 7 days after resolution, or 28 days after an onset that never resolved. |
| `excluded_infection_without_onset` | From 14 days before to 28 days after a positive test with no symptom episode. |
| `excluded_undated_illness` | The participant reported an illness with no date at all. |

Further rules:

- **Relapses.** A further onset within 14 days, with no accepted recovery between, continues the same episode.
- **Positive-test target.** This is separate and never an onset. `positive_test` marks a window holding a positive test's collection day (`uncertain_partial_test` when a window cuts that day). Released cohorts publish no negative tests, so the alternative is `no_reported_positive_test`. Cutoffs within 90 days after a positive are `excluded_recent_positive`.
- **Test linking.** A test links to an episode when collected between 7 days before onset and 14 days after. A COVID-19 participant's other episodes become `unspecified_illness`, never COVID-19.

**Recovery.** The time origin is the onset interval, and day indices count from its first day.

- `sustained_symptom_free` (canonical) resolves at the first run of 2 consecutive local days with completed symptom-free surveys after onset. The resolution interval runs from the day after the last symptomatic survey to the run's first day, so survey gaps widen it. Otherwise the episode is right-censored at its last survey day (`no_qualifying_run`), or at onset when there is no survey after it (`no_follow_up`).
- `self_reported_recovery` (Stanford phase 1) is the participant's own recovery date. It is a distinct outcome, because feeling recovered is not being symptom-free: 135 phase 1 survey rows marked "Recovered from illness" still report symptoms. A date is rejected (the episode is censored) when it precedes onset, falls after the next episode's onset, or a survey within 7 days after it reports symptoms. With several dates the latest is kept, since an earlier recovery followed by another was not lasting.

**Confidence.** `confirmed` means a linked positive test or a source's lab-confirmed infection (CMU shedding or seroconversion). `uncertain` means the source says not infected (CMU). Everything else is `probable`.

## Clocks

- **Stanford.** Both releases give local wall time in an undisclosed US zone, and the authors shifted every date "to obscure PHI" (phase 2 has dates in 2027-2028). No real UTC instant exists, so labels and wearable rows share one floating clock (`clock: floating_local_shifted` in the manifest): local day D is written into `*_utc` fields as D 00:00Z. Within a dataset, order and durations are exact. Never join these times with another dataset or with real UTC data. Any Stanford wearable feature adapter must read the CSVs' naive timestamps the same way.
- **CMU.** The labels carry no calendar dates: study day N after the challenge is written as 2000-01-01 + N days (`clock: relative_to_challenge`).

Evidence for the Stanford clock: every build totals steps by hour of day across the archive (`clock_check_steps_share_by_hour` in the audit). The phase 1 totals bottom out at 02:00-03:00 (0.2% of steps an hour) and peak around noon to 17:00. That is local wall time; US data on UTC would trough around 08:00-12:00.

## Source quirks handled

- **Stanford phase 1.** 637 of 1,461 survey rows have no answer at all; they are not completed surveys. 30 days have several reports, and the worst state wins. One participant has three device files (`_1`/`_2`/`_3`), and four have `_longterm` files. All are counted per day as one participant.
- **Stanford phase 2.** 28 members hold a failed BigQuery export's error text instead of a CSV, 2 hold an error in the query string, and 16 are blank. All are counted as member states, and any other unexpected header is refused. Files start with a blank line.
- **CMU.** BCS rows carry no daily Jackson scores in the five-study file (BCS used a clinician checklist), so they are excluded and counted. Assessment times are undocumented, so a first symptomatic rating on day N gives an onset interval of days N-1 to N. Follow-up ends with quarantine (day 5, or day 6 for influenza), so most recoveries are right-censored and exact recovery days cannot be trained from it.

## Verification

Synthetic tests (`tests/data/clinical/`) cover:

- every definition on hand-built timelines (horizons, ongoing and washout exclusions, negatives needing full survey coverage, partial onsets, test linking and the test target, asymptomatic infection, undated illness, relapse merging, both recovery endpoints and their rejection rules, and confidence);
- generated workbooks and archives in both Stanford layouts (including export-error and blank members, and macOS metadata);
- contract validity, byte-identical rebuilds, read-only output, tamper detection, admission refusal and unexpected archive members;
- the CMU adapter and its registration gate on a synthetic five-study file;
- that reports contain no participant ids or dates.
