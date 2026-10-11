# Shared contracts v0.1

This document explains caller semantics so the three lanes can work in parallel. The executable contracts are authoritative and this page summarises them:

| What | Where | Edit by hand? |
|---|---|---|
| Pydantic models (single source of truth) | `src/hachi/contracts/` | Yes |
| JSON Schema | `contracts/schema/hachi.schema.json` | No, `make build` |
| TypeScript types | `contracts/typescript/index.ts` (package `@hachi/contracts`) | No, `make build` |
| Synthetic fixtures, valid and invalid | `contracts/fixtures/` (defined in `contracts/scripts/build_fixtures.py`) | No, `make build` |

Changes affecting both sides require both owners' review. CI fails if a generated file no longer matches the models.

Every model is strict and immutable and rejects unknown fields. Strings are never coerced to numbers. Timestamps ending `_utc`, plus `as_of`, must be UTC (`Z` or `+00:00`); naive and other-offset timestamps are rejected. Ids are letters, digits, `_` and `-`, so an id can never act as a filesystem path.

## One real caller

The dashboard requests a report with `subject_id`, an explicit UTC `as_of`, and a task. The backend resolves a dataset snapshot and frozen model artifact, reads only eligible observations, invokes the model, persists the output with provenance, and returns a `ReportJob` in state `queued`. The UI polls `GET /v1/reports/{id}` until the job is `completed`, then shows its `ReportResult`: a result, or a specific unavailable/error state.

```json
{
  "schema_version": "0.1",
  "subject_id": "synthetic-001",
  "as_of": "2026-10-10T07:00:00Z",
  "task": "physiology_forecast",
  "resolution": "hour",
  "horizon_hours": 24,
  "metrics": ["heart_rate", "steps"]
}
```

This request is the `ReportRequest/physiology-forecast-hourly` fixture, not a recorded participant. Physiology forecasts take `resolution: "hour"` (1–24 hourly bins) or `resolution: "day"` (the next completed local day). Illness onset takes `horizon_hours` of 24, 48 or 72. Recovery takes the `episode_id` of an ongoing episode. Alertness is requested through `POST /v1/scenarios`, not as a report.

## Data tables

| Table | Model | Boundary invariant |
|---|---|---|
| Observation | `Observation` | Canonical unit per metric; start ≤ end; impossible values rejected; `availability` is `observed` (source-recorded) or `assumed` with a named `availability_rule`, never silently treated as observed; timezone provenance explicit |
| Aggregate | `Aggregate` | Hour bins span exactly one hour; day bins span local midnight to midnight in `tz_name` (23/25 h across DST); an empty bin has `value: null` with a `null_reason`, never zero; aggregation must suit the metric (steps are summed, never averaged); values name their `source_ids` |
| Outcome | `Outcome` = `SymptomEpisode` \| `TestResult` \| `StatusUnknown` | Onset and resolution are intervals; resolved episodes need a resolution definition within follow-up; censored episodes carry none; a test date is a separate record, never an onset; unknown status is explicit, not healthy |
| Split manifest | `SplitManifest` | Train/validation/test subjects are pairwise disjoint; whole-subject exclusions are unassigned; immutable once `test_opened_at_utc` is set |
| Run manifest | `RunManifest` | Git SHA (and whether the tree was dirty), config, dataset, split, environment and artifact digests; ordered unique features; metrics paths stay under their storage root |

Rows carry no `schema_version`; a table snapshot records the version it was written with. Keep identity mapping outside the analytical tables and outside Git. Raw source names (for example "Alex's Apple Watch") can contain personal names, so observations carry a `source_kind` and a pseudonymous `source_id` instead. Raw files are immutable; derived tables can be regenerated. For date-shifted research datasets, preserve relative-day coordinates and explicitly synthetic anchors rather than inventing real calendar dates.

The cutoff rule lives in `hachi.contracts.causality`: an observation may inform a prediction at a cutoff only if it has ended *and* become available by then, so a backdated entry is excluded. An outcome label is known at a cutoff only once it has been recorded. `local_day_bounds` gives the UTC instants of a local day for any IANA timezone.

## Feature semantics

- Preserve timezone and daylight-saving behavior. UTC identifies an instant; local time determines sleep and day boundaries. Define overlap handling for sleep intervals and cross-midnight episodes.
- Retain metric identity. Apple SDNN (`hrv_sdnn`) is not RMSSD (`hrv_rmssd`). Overnight resting-HR estimates are not interchangeable with vendor daily resting HR (`resting_heart_rate_vendor`). Wrist-temperature deviation is not core body temperature. Summary sleep (`sleep_asleep_unspecified`) is distinct from staged sleep.
- Deduplicate overlapping iPhone/Watch/app sources with documented precedence. Do not sum competing step totals. Quarantine unknown units instead of guessing.
- Use values and missingness masks. Do not fill future gaps using later observations. Never turn unknown steps into zero to manufacture resting periods.
- Start from a small compatible feature set, then add signals by ablation. New metrics are added to `hachi.contracts.metrics` with one canonical unit. Preserve original higher-frequency data for model-specific adapters; do not pretend an hourly table supplies raw PPG or PSG.
- No global normalization fitted on held-out subjects. A held-out user's historical prefix may support causal personalization; freeze the policy before evaluation.

## API surface

| Method/path | Body → response | Purpose |
|---|---|---|
| `POST /v1/imports` | upload → `ImportStatus` | Stream upload, declare source/timezone, enqueue validation |
| `GET /v1/imports/{id}` | → `ImportStatus` | Pending/running/succeeded/failed, per-bucket record counts, aggregate rejection/quarantine reasons, actionable failure |
| `GET /v1/subjects/{id}/coverage` | → `Coverage` | Available metrics, time span, gaps, sources, and which tasks the data can support |
| `POST /v1/reports` | `ReportRequest` → `ReportJob` | Validated report request; enqueue idempotent inference |
| `GET /v1/reports/{id}` | → `ReportJob` | Job state and, once completed, the `ReportResult` |
| `POST /v1/subjects/{id}/observations` | `SelfReportRequest` | Symptom onset/check-in/resolution, test results, alertness ratings, PVT results and confounders, each with separate event and entry times |
| `POST /v1/scenarios` | `ScenarioRequest` → `ReportResult` | Bedtime/wake-time schedules, timezone and explicit assumptions; answered synchronously with an `alertness` result |
| `DELETE /v1/subjects/{id}` | | Confirmed deletion of subject data and derived personal artifacts |
| `GET /healthz` | → `HealthStatus` | Process readiness plus code/artifact versions, no participant data |

Every non-2xx response is an `ApiError` with a stable `error_code` and a `request_id`. Validate and authorize ids server-side; never accept an arbitrary filesystem path from the browser. Input hashes plus model/version/task form an idempotency key so retries do not rerun expensive jobs.

Transport conventions:

- The import body is the export file itself. The declared source comes as query parameters: `subject_id`, `tz_name`, `source_format` and `data_mode`.
- `DELETE` takes `?confirm=<subject id>`.
- A repeated idempotent request answers 200 with the existing import or job. A new one answers 202.

The implementation and its served-artifact layout are described in [src/hachi/api/README.md](../src/hachi/api/README.md).

## Result envelope

`ReportResult` is a tagged union. Narrow on `status`, then on `task`:

- `status: "ok"` has exactly one payload, keyed by its task: `forecast`, `anomaly`, `illness_onset`, `recovery` or `alertness`. A payload under the wrong key is rejected.
- `status: "unavailable"` has a `reason_code`, at least one `requirement`, and whatever `provenance` was resolved before stopping.
- `status: "error"` has a stable `error_code` and a message that is safe to show.

Missing evidence is `unavailable`, never a probability of zero.

Every result carries `schema_version`, `report_id`, `subject_id`, `as_of`, `data_mode` (`real` or `synthetic`), `generated_at_utc`, `git_sha`, `warnings` and `replay` (set when a saved run is shown instead of a live one). `ok` results also carry full `provenance`: dataset snapshot, artifact id and hash, and feature coverage. Only an alertness simulation may omit the dataset snapshot. An unavailable result may lack an artifact precisely because none exists.

Task payloads:

- **Forecast:** per-metric series in the canonical unit; contiguous points starting at or after `as_of`; `lower ≤ median ≤ upper` within metric bounds; `nominal_coverage` and `interval_calibration` (`uncalibrated` until held-out coverage is measured); optional personal baseline ending by `as_of`. Day points name their `local_date`.
- **Anomaly:** score definition, `alert_state` (`no_alert`, `alert` or `abstained`) consistent with score and threshold, a baseline window and a timeline ending by `as_of`, changed features, and observed alert burden once measured. There is no illness probability field.
- **Illness:** onset probability for a 24/48/72-hour horizon, target definition, calibration cohort/version/method, and distribution status.
- **Recovery:** a non-increasing survival curve from day 0, endpoint definition, and median, all limited to the supported follow-up.
- **Alertness:** `simulation` or `validated_prediction`, scale, assumptions and one curve per schedule. A simulation must not carry a `validation`, so it cannot show an accuracy badge.

Minimal unavailable result for early UI work (`contracts/fixtures/ReportResult/unavailable-illness-onset.json`):

```json
{
  "schema_version": "0.1",
  "report_id": "synthetic-report-unavailable",
  "subject_id": "synthetic-001",
  "as_of": "2026-10-10T07:00:00Z",
  "data_mode": "synthetic",
  "generated_at_utc": "2026-10-10T07:00:05Z",
  "git_sha": "0000000000000000000000000000000000000000",
  "warnings": [],
  "replay": null,
  "status": "unavailable",
  "task": "illness_onset",
  "reason_code": "NO_VALIDATED_ILLNESS_ARTIFACT",
  "requirements": ["Labeled cohort evaluation and calibrated artifact"],
  "provenance": null
}
```

## Fixtures

`contracts/fixtures/<Document>/` holds valid synthetic fixtures for every document. They cover each task's `ok` result, unavailable and error results, sparse and empty history, every import state including failure, and a 25-hour DST day. `contracts/fixtures/invalid/<Document>/` holds payloads that must be rejected, and `invalid/expectations.json` records the reason for each. Every fixture is marked synthetic (`synthetic-` ids, `data_mode: "synthetic"`), and tests enforce this. Fixture values are illustrative shapes, not model output.

## Artifact handoff

Ezzy supplies an immutable artifact directory plus run manifest and inference entry point. Justin validates feature/schema compatibility and checksum at load, refuses incomplete artifacts, and exposes artifact identity in responses. CoffeeCoder consumes generated types and never reconstructs model probabilities in the browser. Shared contract changes land before dependent implementation PRs.
