# Illness and recovery labels (#8): cohorts, snapshots and access

What #8 delivered: the locked outcome definitions, the Stanford COVID-19 and CMU Common Cold label snapshots, and where each illness cohort stands. Everything here is aggregate. Participant-level tables stay in approved storage (`$HACHI_DATA_ROOT/derived/`, and read-only on the GX10 at `~/hachi/data/derived/`). The per-dataset machine reports for the current snapshots are beside this file:

- [`clinical-labels-2-stanford-covid19-wearables-2020-nbe.json`](clinical-labels-2-stanford-covid19-wearables-2020-nbe.json) / [`.md`](clinical-labels-2-stanford-covid19-wearables-2020-nbe.md)
- [`clinical-labels-2-stanford-covid19-wearables-phase2-2022-nm.json`](clinical-labels-2-stanford-covid19-wearables-phase2-2022-nm.json) / [`.md`](clinical-labels-2-stanford-covid19-wearables-phase2-2022-nm.md)
- [`clinical-labels-2-cmu-common-cold-project-retrieved-2026-10-10.json`](clinical-labels-2-cmu-common-cold-project-retrieved-2026-10-10.json) / [`.md`](clinical-labels-2-cmu-common-cold-project-retrieved-2026-10-10.md)

The `clinical-labels-1` snapshots (first published in PR #58; reports `clinical-labels-1-*`) are superseded. Every table and the audit are byte-identical to `clinical-labels-2`, which only adds `symptom_scores.parquet`. Both stay in place, read-only.

Code and definitions: [`src/hachi/data/clinical/`](../../src/hachi/data/clinical/README.md) and [`configs/outcomes/`](../../configs/outcomes/definitions.toml) (`definitions_version = "outcomes-1"`).

## Snapshots

| | Stanford phase 1 (Mishra 2020) | Stanford phase 2 (Alavi 2022) |
|---|---|---|
| Snapshot id | `clinical-labels-2-stanford-covid19-wearables-2020-nbe-6a864b03b2d3` | `clinical-labels-2-stanford-covid19-wearables-phase2-2022-nm-bbbca036d9e5` |
| `DatasetSnapshotRef` | `stanford-covid19-wearables` / `2020-nbe` / `6a864b03b2d3ddf05abc42b699679dba39f1909bad2c3053c4b8adf4108faf09` | `stanford-covid19-wearables-phase2` / `2022-nm` / `bbbca036d9e5500351ddfab1b43e2c9622626389c1f6f881244035cfc300cd70` |
| Sources (registry-pinned) | `COVID-19-Wearables.zip` (378,380,920 B, `52ca976e…80f4`) + `41551_2020_640_MOESM3_ESM.xlsx` (4,041,311 B, `cf89b4b7…98ec`) | `COVID-19-Phase2-Wearables.zip` (5,537,624,129 B, `c90b1314…c994`) + `41591_2021_1593_MOESM3_ESM.xlsx` (25,369 B, `166f8465…08e3b3`) |
| Built from | commit `18ec9fc`, clean tree, 10 s | commit `18ec9fc`, clean tree, 235 s (about 1.4 GB peak RSS) |
| Rows | outcomes 246, episodes 59, recovery 118, onset_windows 14,481, subjects 121, status_intervals 562, surveys 794, symptom_scores 794, wearable_days 11,729 | outcomes 2,337, episodes 66, recovery 66, onset_windows 365,377, subjects 2,122, status_intervals 2,122, surveys 0, symptom_scores 0, wearable_days 266,348 |
| Locations | Mac `$HACHI_DATA_ROOT/derived/<id>/`; GX10 `~/hachi/data/derived/<id>/` (read-only) | same |

**CMU Common Cold Project** (aggregated five-study file): snapshot `clinical-labels-2-cmu-common-cold-project-retrieved-2026-10-10-7c1429b102eb`. Its `DatasetSnapshotRef` is `cmu-common-cold-project` / `retrieved-2026-10-10` / `7c1429b102ebf5bcb5c0f94db0aba6c1e290d1b0b78aeae68c7105b3cfda38c3`. The source is `Aggregated Cold Study (Studies 1-5) .zip` (60,512,756 B, `6a0d7443…d348`), member `FIVE_STUDY_DATA.dat`. It was built from commit `b504950` on a clean tree in 0.7 s, after the CMU Data Analysis Form was submitted on 2026-10-11 (recorded in `configs/outcomes/cmu-common-cold-project.toml`). Rows: outcomes 6,520, episodes 697, recovery 697, onset_windows 5,113, subjects 1,016, status_intervals 3,018, surveys 5,107, symptom_scores 5,107, wearable_days 0. It sits at the same locations; the CMU agreement allows the shared GX10 login because all three teammates registered.

Built with `HACHI_DATA_ROOT=/Volumes/T7/Stockpile/hachi.datasets uv run python -I -m hachi.data.clinical build <dataset_id> --report-dir reports/data`, from a clean tree.

## Verification

- **`verify --full`** passes for all three snapshots: every file matches `SHA256SUMS` and the manifest, the snapshot hash and directory name agree, and every outcome row re-validates against the shared contracts.
- **Deterministic rebuild.** An independent phase 1 build into a scratch directory gave the same snapshot id and a byte-identical `SHA256SUMS`, covering all eleven files including the manifest and audit. The phase 2 build reproduced every table and the audit of the earlier `clinical-labels-1` phase 2 build byte for byte.
- **`reconcile`** re-reads each source workbook and checks the snapshot by a separate route, without the label engine. It found 0 mismatches. Phase 1 checks: 59 episode onsets are reported dates; reported onsets are accounted for in all 47 participants (merged relapses included); positive tests equal the reported diagnosis dates in all 47; 794 answered survey days have the state their raw answers imply; all 33 accepted self-reported recoveries are reported dates; and 48 episodes whose onset day is a cutoff are `positive` or excluded there. Phase 2 checks: all 84 positives' test dates are matched, all 66 episode onsets are reported dates, and the 66 own-onset cutoffs are positive.
- **CMU `reconcile`** re-parses `FIVE_STUDY_DATA.dat` independently and checks the snapshot from raw cells. It found 0 mismatches:
  - the participant set (1,016);
  - 5,107 daily states and adjusted scores;
  - for all 1,016 participants, an episode exactly when a symptomatic day exists, and shedding cultures that match;
  - 697 onsets on the first symptomatic day;
  - 590 infected episodes `confirmed` and 107 uninfected `uncertain`.

  An independent CMU rebuild was byte-identical. No CMU row or participant id was printed or read into a conversation; every check reports counts only.
- **Paper cross-check.** Phase 1 yields 27 test-confirmed COVID-19 episodes, matching the paper's "32 COVID-19-positive participants (27 confirmed)". Phase 2 yields 84 positives, 66 with a symptom onset.
- **GX10.** All three snapshots and both Stanford label workbooks are on the GX10 read-only, and `sha256sum -c SHA256SUMS` passes in each directory.
- **Synthetic tests** (`tests/data/clinical/`, 37 tests) cover every definition, both archive layouts with their quirks, the CMU adapter and its gate, tamper detection, read-only output, admission refusal and report sanitization.

## Cohort audit

Counts are participants unless stated otherwise. Day precision throughout. On the floating clock, the onset interval is one local day for every episode in both cohorts; the time zone is undisclosed and the dates are shifted.

| | Phase 1 | Phase 2 |
|---|---:|---:|
| Participants (wearable archive ∪ label tables) | 121 | 2,122 |
| with wearable records | 118 | 2,122 |
| in the label tables / with wearables / without wearables | 47 / 44 / 3 | 84 / 84 / 0 |
| with completed daily surveys | 35 | 0 (none released) |
| Controls outside the label tables | 74, with 6,252 wearable days (median 90 days each) and **0 survey days** | 2,038, with 252,787 wearable days (median 120) and **0 survey days** |
| Episodes | 59 | 66 |
| COVID-19 confirmed by a linked positive test / probable | 27 / 2 | 61 / 0 |
| other illness / influenza B / unspecified (other episodes of COVID-19 participants, or a test 15+ days off) | 15 / 1 / 14 | 0 / 0 / 5 |
| Relapse onsets merged into an episode | 3 | 0 |
| COVID-19 episodes with ≥14 HR days in the 28 days before onset | 28 of 29 | 60 of 61 |
| Positive tests (no negative tests released) | 36: 29 linked, 7 unlinked | 84: 61 linked, 23 unlinked (18 asymptomatic, 5 far from onset) |
| Test day − onset day, linked tests | median 3 (IQR 1–5, range 0–14) | median 2 (IQR 1–3, range −5 to 8) |
| Survey rows / answered survey days / rows with no answer | 1,461 / 794 / 637 | none |
| Per-day severity (`symptom_scores`, one row per answered survey day) | 794 days from 35 participants; 544 with at least one symptom; max severity 1/2/3/4/5 on 186/84/113/113/48 days | none |
| Unknown-status periods (no survey, outside episodes) | 151 periods, 11,602 days | 2,187 periods, 367,433 days |

**Onset windows at local midnight.** Phase 1 has 14,481 cutoffs, 11,638 of them with wearable records the day before. Phase 2 has 365,377 cutoffs.

| Label | P1 24 h | P1 48 h | P1 72 h | P2 24 h | P2 48 h | P2 72 h |
|---|---:|---:|---:|---:|---:|---:|
| positive | 47 | 94 | 140 | 66 | 132 | 198 |
| negative (survey-confirmed) | 180 | 116 | 84 | 0 | 0 | 0 |
| **at-risk denominator** | **227** | **210** | **224** | **66** | **132** | **198** |
| participants with a positive window | 40 | 40 | 40 | 66 | 66 | 66 |
| uncertain_unexplained_symptoms | 241 | 319 | 370 | 0 | 0 | 0 |
| unknown_no_survey | 11,826 | 11,663 | 11,496 | 362,939 | 360,788 | 358,638 |
| unknown_follow_up_ended | 0 | 102 | 204 | 0 | 2,085 | 4,169 |
| excluded_ongoing_episode | 1,530 | 1,530 | 1,530 | 0 | 0 | 0 |
| excluded_washout | 474 | 474 | 474 | 1,561 | 1,561 | 1,561 |
| excluded_infection_without_onset | 89 | 89 | 89 | 811 | 811 | 811 |
| excluded_undated_illness | 94 | 94 | 94 | 0 | 0 | 0 |

Positive-test target, 24 h: phase 1 has 30 `positive_test` windows and phase 2 has 84. The rest are `no_reported_positive_test` or `excluded_recent_positive`; no negative tests were released.

**Recovery and censoring.**

| Endpoint | Phase 1 | Phase 2 |
|---|---|---|
| `outcomes-1-sustained-symptom-free-2d` (canonical) | 59 episodes: 15 resolved; censored with no qualifying run 19, no follow-up 25. Resolution day index (from onset day 0): earliest median 0 (IQR 0–38), latest median 35 (IQR 21–49.5). Censored follow-up median 0 days (IQR 0–56, max 149) | 66 episodes, all `no_follow_up` (nothing released after onset) |
| `outcomes-1-self-reported-recovery` (distinct outcome) | 33 resolved (day index median 13, IQR 6–23); 7 rejected as contradicted by a later symptomatic survey, 2 dates before onset rejected, 14 earlier dates superseded by a later one; 19 not reported | n/a |

**Clock check (steps share by hour of day).** Phase 1 troughs at 02–03 h (0.25% an hour) and peaks around noon to 17 h (6.9%), which is local wall time. Phase 2 troughs at 01–02 h (0.4–0.5%) and peaks at 12–15 h (7.4–7.5%).

**Source checks.**
- Phase 1: 17 diagnosis, 17 recovery and 3 onset entries are `NaT`. One participant reports an illness with no date at all; their windows are `excluded_undated_illness`. 30 survey days have several reports, 2 of them conflicting, and the worst state wins. 3 labeled participants have no wearable file.
- Phase 2 archive: 4,200 members read; 30 hold export-error text and 16 are blank; 4,251 `__MACOSX` entries are ignored; 14 rows are unparseable (repeated headers); 1.47 billion HR records and 49.9 million step records.

## CMU Common Cold Project audit

Healthy adults were inoculated on quarantine Day 0 and rated eight Modified Jackson symptoms (0-4) daily until the end of quarantine. That is Day 5, or Day 6 for influenza. There are no wearables and no calendar dates: study day N is written as 2000-01-01 + N days (`clock: relative_to_challenge`).

| | Count |
|---|---:|
| Participants in the five-study file | 1,415 (BCS 399, PCS1 276, PCS2 334, PCS3 213, PMBC 193) |
| Excluded: BCS has no daily Jackson scores in this file | 399 |
| Participants with daily scores | 1,016 (infected 784, not infected 232, by `post.infected`) |
| Answered quarantine days: symptomatic / symptom-free / intermediate | 2,110 / 2,822 / 175 |
| Participants with a gap in their quarantine days | 2 |
| Non-0/1 codes counted and treated as missing | 1 (`cold`) |
| Episodes (first day with an adjusted Jackson score of at least 2) | 697: rhinovirus 574 confirmed + 99 uncertain (not infected); influenza 16 confirmed + 8 uncertain |
| Participants without a symptomatic onset | 319 |
| Shedding cultures (positive / negative) | rhinovirus and other viruses (contract pathogen `other`) 2,288 / 2,543; influenza 69 / 159 |
| Positive cultures linked to no episode (asymptomatic infection or outside the link window) | 481 |

**Onset precision.** Assessment times are undocumented. A first symptomatic rating on day N therefore places onset in days N-1 to N, a 2-day interval. No 24 h window can contain a 2-day interval, so every CMU 24 h window that overlaps an onset is `uncertain_partial_onset`. CMU supports onset labels at 48 and 72 h only, and they are exploratory and symptom-only.

| Label | 24 h | 48 h | 72 h |
|---|---:|---:|---:|
| positive | 0 | 444 | 609 |
| negative (symptom-free every day) | 967 | 645 | 443 |
| **at-risk denominator** | **967** | **1,089** | **1,052** |
| uncertain_partial_onset | 1,141 | 862 | 753 |
| uncertain_unexplained_symptoms | 33 | 39 | 34 |
| excluded_ongoing_episode / washout / infection without onset | 1,822 / 304 / 843 | same | same |
| unknown_follow_up_ended / unknown_no_survey | 0 / 3 | 151 / 3 | 302 / 3 |

**Recovery (`outcomes-1-sustained-symptom-free-2d`).**
- 697 episodes: 170 resolved, and the rest right-censored at the end of quarantine (511 with no qualifying run, 16 with no follow-up after onset).
- Resolved episodes reach their resolution interval at day index 2–5 from the onset interval's first day (median 2, IQR 2–3).
- Censored follow-up runs a median of 4 days (IQR 3–5, max 6).
- Exact recovery days beyond quarantine cannot be learned from this cohort.

**Severity.** `symptom_scores` holds the adjusted Jackson total and the "have a cold?" answer for every answered day (5,107 rows), available at the end of that day.

## What each cohort can and cannot support

| Capability | Stanford phase 1 | Stanford phase 2 | CMU Common Cold |
|---|---|---|---|
| Wearable onset prediction, at-risk classification (#13) | Yes, evaluation-sized: survey-confirmed negatives exist but are few (180 at 24 h) | No negatives: no surveys were released, so every non-episode window is `unknown_no_survey` | No wearables. Symptom-only onset at 48/72 h (exploratory) |
| Onset detection lead time / sensitivity (#9, #13) | Yes | Yes, the main use (66 onsets, 61 test-confirmed) | No wearables |
| Positive-test target | 36 positive tests, no negatives released | 84 positive tests, no negatives released | Daily shedding cultures, positive and negative (5,059) |
| Healthy-period alert burden (#9) | Only from `observed_symptom_free` survey days (the 24 h negatives above) | None observed | No wearables |
| Recovery (#14) | Small: 15 sustained resolutions, 33 accepted self-reported recoveries, the rest censored | None: no follow-up after onset is released | The main recovery cohort: 697 episodes, 170 resolved, 527 right-censored at the end of quarantine; symptom predictors only |

COVID-19 labels are not colds, and CMU's rhinovirus, influenza, RSV and coronavirus 229E challenges are not COVID-19. Phase 1's 14 other episodes in COVID-19 participants are `unspecified_illness`, and its 15 other-illness and 1 influenza B episodes keep their own categories. Phase 2's onset target is COVID-19 symptom onset only. CMU categories name the challenge virus.

## Access

| Cohort | State |
|---|---|
| Stanford COVID-19 wearables, phase 1 and phase 2 | Public; downloaded, labels built (above) |
| CMU Common Cold Project | Registered by all three teammates. The CMU Data Analysis Form was submitted on 2026-10-11 by Justin, Ezzy and CoffeeCoder, via the Google Form linked from cmu.edu/common-cold-project; no reference number was returned. Labels are built (above) |
| CovIdentify 1.0.0 (PhysioNet) | `rejected_for_task`. Abandoned on 2026-10-11 by Justin's decision: the PhysioNet credential review cannot finish within the project timeline. No data was obtained |
| Homekit2020, Evidation ILI 2019-2020 (Synapse) | `rejected_for_task`. Not available for this project: Synapse certification and profile validation were never completed, so no data was obtained |

## Limitations and open items

- **CMU storage security.** CMU's agreement asks for data "secured using appropriate technology"; the target is encrypted storage. The T7 and the GX10 disk are not encrypted yet, and the GX10 still allows password SSH on its private lab network. Justin accepted this interim state on 2026-10-11 and plans to encrypt. This is not a gate on #8.
- **No training-sized wearable illness cohort.** With CovIdentify and the Synapse cohorts out, the only wearable-paired illness labels are the Stanford cohorts, which are evaluation-sized. #13 must report that limit rather than claim a calibrated onset model. CMU adds symptom-only recovery and onset labels with no wearables.
- **CMU publications.** After publishing anything that uses CMU data, report it with CMU's Data Set Publication Form.
