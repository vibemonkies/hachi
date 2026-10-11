# Shared contracts: implementation brief v0

This document fixes caller semantics so the three lanes can start together. The contracts issue produces executable validation schemas, generated client types, and synthetic fixtures. Changes affecting both sides require both owners' review.

## One real caller

The dashboard requests a report with `subject_id`, an explicit UTC `as_of`, and a task. The backend resolves a dataset snapshot and frozen model artifact, reads only eligible observations, invokes the model, persists the output with provenance, and returns a job id. The UI polls for the result and shows either a result or a specific unavailable/error state.

```json
{
  "subject_id": "local-pseudonym-001",
  "as_of": "2026-10-10T07:00:00Z",
  "task": "physiology_forecast",
  "horizon_hours": 24
}
```

This request is illustrative, not a recorded participant or prediction.

## Data tables

| Table | Required fields | Boundary invariant |
|---|---|---|
| Observation | dataset_id, subject_id, record_id, source/device, metric, value, unit, start_utc, end_utc, available_at_utc, timezone/offset provenance | Valid units and intervals; no inferred availability silently treated as observed |
| Aggregate | subject_id, metric, resolution, interval_start/end, value or null, observed_count, coverage, source, pipeline_version | Empty is missing, never zero; provenance survives aggregation |
| Outcome | subject_id, episode_id, kind, onset interval, resolution interval, observed_at, label_source, confidence, censoring | Symptoms, positive tests, recovery, and unknown status are distinct |
| Split manifest | dataset snapshot hash, subject partitions, time boundaries, exclusions, lookback/horizon, seed, schema version | Immutable after test is opened; identities and overlapping events cannot cross partitions |
| Run manifest | git SHA, configuration hash, dataset/split hashes, feature order, model/checkpoint revision, environment digest, seed, artifact checksum, metrics paths | Every prediction resolves to its generating code and artifact |

Keep identity mapping outside the analytical tables and outside Git. Raw files are immutable; derived tables can be regenerated. For date-shifted research datasets, preserve relative-day coordinates and explicitly synthetic anchors rather than inventing real calendar dates.

## Feature semantics

- Preserve timezone and daylight-saving behavior. UTC identifies an instant; local time determines sleep and day boundaries. Define overlap handling for sleep intervals and cross-midnight episodes.
- Retain metric identity: Apple SDNN is not RMSSD; overnight resting-HR estimates are not interchangeable with vendor daily resting HR; wrist-temperature deviation is not core body temperature.
- Deduplicate overlapping iPhone/Watch/app sources with documented precedence. Do not sum competing step totals. Quarantine unknown units instead of guessing.
- Use values and missingness masks. Do not fill future gaps using later observations. Never turn unknown steps into zero to manufacture resting periods.
- Start from a small compatible feature set, then add signals by ablation. Preserve original higher-frequency data for model-specific adapters; do not pretend an hourly table supplies raw PPG or PSG.
- No global normalization fitted on held-out subjects. A held-out user's historical prefix may support causal personalization; freeze the policy before evaluation.

## Proposed API surface

| Method/path | Purpose |
|---|---|
| `POST /v1/imports` | Stream upload, declare source/timezone, enqueue validation; return import id |
| `GET /v1/imports/{id}` | Pending/running/succeeded/failed, counts, rejected records, actionable error |
| `GET /v1/subjects/{id}/coverage` | Available metrics, time span, missingness, provenance |
| `POST /v1/reports` | Validated forecast request; enqueue idempotent inference |
| `GET /v1/reports/{id}` | Structured result and artifact provenance |
| `POST /v1/subjects/{id}/observations` | Timestamped self-reports/PVT results; preserve entry time and event time |
| `POST /v1/scenarios` | Bedtime, wake time, timezone, assumptions; conditional alertness output |
| `DELETE /v1/subjects/{id}` | Confirmed deletion of subject data and derived personal artifacts |
| `GET /healthz` | Process readiness plus code/artifact versions, no participant data |

Validate and authorize ids server-side; never accept an arbitrary filesystem path from the browser. Use stable error codes and request ids. Input hashes plus model/version/task form an idempotency key so retries do not rerun expensive jobs.

## Result envelope

Use a tagged union: `status=ok` has one task-specific payload; `status=unavailable` has `reason_code` and requirements; `status=error` has a safe error code. Do not represent missing evidence as a probability of zero.

All results carry schema_version, report_id, subject_id, as_of, data_mode (`real` or `synthetic`), dataset snapshot, git SHA, artifact id/hash, feature coverage, and warnings. Task payloads:

- Forecast: metric/unit, horizon and timestamps, median, interval bounds and nominal coverage; label uncalibrated intervals honestly.
- Anomaly: score definition, alert state, baseline window, changed features, observed alert burden if measured; no illness probability field.
- Illness: cumulative onset probability for a defined horizon, target definition, calibration cohort/version, and out-of-distribution status.
- Recovery: survival curve or quantiles with censoring/endpoint definition, conditional on symptoms known at cutoff.
- Alertness: `simulation` or `validated_prediction`, units/scale, assumptions and scenario parameters. Simulated curves cannot use a generic accuracy badge.

Minimal unavailable fixture for early UI work:

```json
{
  "schema_version": "0.1",
  "report_id": "fixture-unavailable",
  "subject_id": "synthetic-001",
  "as_of": "2026-10-10T07:00:00Z",
  "data_mode": "synthetic",
  "status": "unavailable",
  "task": "illness_onset",
  "reason_code": "NO_VALIDATED_ILLNESS_ARTIFACT",
  "requirements": ["Labeled cohort evaluation and calibrated artifact"]
}
```

## Artifact handoff

Ezzy supplies an immutable artifact directory plus run manifest and inference entry point. Justin validates feature/schema compatibility and checksum at load, refuses incomplete artifacts, and exposes artifact identity in responses. CoffeeCoder consumes generated types and never reconstructs model probabilities in the browser. Shared contract changes land before dependent implementation PRs.
