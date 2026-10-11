# Import/report API — issue #16

The local API for the surface in [docs/CONTRACTS.md](../../../docs/CONTRACTS.md). Every request
body and response is a contract document (`@hachi/contracts` on the web side). FastAPI
lives in the optional `api` extra.

## Run it

One process per developer. Each binds to loopback, on its own port, with its own SQLite
metadata database:

```sh
uv run --extra api python -I -m hachi.api serve --owner justin06lee   # 127.0.0.1:8716
```

| Owner | Port |
|---|---|
| justin06lee | 8716 |
| CoffeeCoder1015 | 8717 |
| ezzy1630 | 8718 |

`HACHI_API_PORT` overrides the port. The server refuses a non-loopback host unless
`--allow-non-loopback` is passed. It also refuses requests whose `Host` header is not a
loopback name, which blocks DNS rebinding.

Configuration comes from the environment. The operator decides every location; the browser
never names a path.

| Variable | Default | Meaning |
|---|---|---|
| `HACHI_OWNER` | — | Owner whose workspace and database are used |
| `HACHI_WORKSPACES` | `~/hachi/workspaces` | Holds `<owner>/state/` (metadata and private import snapshots) |
| `HACHI_DB_PATH` | `<workspace>/state/metadata.sqlite3` | `gpu-run` sets this on the GX10 |
| `HACHI_DATA_ROOT` | — | Approved dataset root. Snapshots are in `derived/<id>/` |
| `HACHI_DATASET_SNAPSHOTS` | — | Comma-separated snapshot ids to serve. Each is verified at startup, and only snapshots built from an admitted archive are served as `real` |
| `HACHI_ARTIFACT_ROOT` | `~/hachi/artifacts` | Served artifacts are in `<artifact_id>/` |
| `HACHI_SERVE_ARTIFACTS` | — | Comma-separated pins: `<artifact_id>@<artifact_sha256>` |
| `HACHI_API_CORS_ORIGINS` | Vite on `localhost`/`127.0.0.1:5173` | Browser origins allowed to call the API |
| `HACHI_GIT_SHA` | `git rev-parse HEAD` | The code identity reported in every result |
| `HACHI_GX10_SSH` | — | SSH destination of the GX10 (e.g. `asus@5asb`) for GPU-backed models |
| `HACHI_GX10_CHECKOUT` | — | GX10 clone of a merged main commit; its `inference.py` must hash like yours |
| `HACHI_GX10_TIMEOUT` | `180` | Seconds one GPU job may take, queue wait included |

`GET /healthz` reports `degraded` when a configured snapshot or artifact was refused. The
reason is logged, and that snapshot or artifact is not used.

## Endpoints

| Method/path | Body → response | Notes |
|---|---|---|
| `POST /v1/imports?subject_id=&tz_name=&source_format=&data_mode=` | raw export → `ImportStatus` | The body is the file itself, with a zip, xml or octet-stream content type. `source_format` is `apple_health_export_zip` or `apple_health_export_xml`. A new import returns 202 `pending`. An identical upload with identical parameters returns 200 and the same import. |
| `GET /v1/imports/{id}` | → `ImportStatus` | `pending` → `running` → `succeeded` or `failed`. A failure carries an actionable `failure.action`. |
| `GET /v1/subjects/{id}/coverage[?as_of=]` | → `Coverage` | With `as_of`, only data available by then is counted. |
| `POST /v1/reports` | `ReportRequest` → `ReportJob` | A new job returns 202 `queued`. An identical request on the same data, artifact and code returns 200 and the same job. |
| `GET /v1/reports/{id}` | → `ReportJob` | `queued` → `running` → `completed`. A failure is a completed job with an `error` result. |
| `POST /v1/subjects/{id}/observations` | `SelfReportRequest` → the same | 201 when an entry was stored. Re-sending an entry exactly is a no-op. Re-sending a changed entry returns 409. A correction is a new `entry_id` with `supersedes` naming the current version: same `kind`, entered no earlier. Forks, deleted ids and wrong episode references are refused. |
| `GET /v1/subjects/{id}/observations[?as_of=&versions=all]` | → `SelfReportHistory` | Current version of each entry, in recording order. `as_of` shows what was known then; `versions=all` lists every version. An empty list for a known subject with none; 404 for an unknown subject. |
| `DELETE /v1/subjects/{id}/observations/{entry_id}?confirm={entry_id}` | → 204 | Erases every version of the entry (SQLite secure delete plus a WAL scrub) and leaves a content-free tombstone, so the ids are never reused. Invalidates the subject's illness/recovery reports. Returns 409 for an onset a recorded resolution refers to. |
| `POST /v1/scenarios` | `ScenarioRequest` → `ReportResult` | `unavailable` until #15's frozen two-process artifact is served. |
| `DELETE /v1/subjects/{id}?confirm={id}` | → 204 | Removes private files first, then the records: if a file can't be removed it answers 500 and keeps every record, so the deletion can be retried. Running jobs, or writes for a subject being deleted, return 409. |
| `GET /healthz` | → `HealthStatus` | Code identity and the served artifact refs. |

Every non-2xx response is an `ApiError`, with `X-Request-Id` set to its `request_id`:

| Code | Status |
|---|---|
| `VALIDATION_FAILED` | 422, or 415 for a wrong content type |
| `SCHEMA_VERSION_UNSUPPORTED` | 400 |
| `NOT_FOUND` | 404 |
| `CONFLICT` | 409 |
| `PAYLOAD_TOO_LARGE` | 413 |
| `INTERNAL_ERROR` | 500 |

Field issues name a location and a rule. They never echo submitted values.

## What a report does

1. Resolves the subject. A configured dataset snapshot comes first, then the subject's latest succeeded import.
2. Selects a served artifact whose declared input the data can supply.
3. Reads history the way the evaluator does:
   - The cutoff is `as_of` rounded down to the hour.
   - History is the inputs available by that cutoff, in the `lookback_hours` window before it.
   - Targets are the next whole UTC hours from `as_of`.
4. Calls the frozen model's own `predict`.

Anything missing becomes `unavailable` with a reason and the provenance resolved so far:

- a task without a validated artifact
- too few observed hours
- a subject whose data the artifact cannot read

Today that covers anomaly, illness, recovery and daily forecasts, plus an Apple import served
with an hourly-feature model.

Failures become `error` results:

- `ARTIFACT_INCOMPATIBLE`: an `as_of` before the model's fit
- `GPU_UNAVAILABLE`: a GPU artifact this instance cannot reach
- `DATA_READ_FAILED` and `INFERENCE_FAILED`

#9's baselines give medians only, so their forecasts are point-only: `interval_calibration`
is `"none"`, and `nominal_coverage` and every point's `lower`/`upper` are null. A forecast
shows an interval only when the model gives one for every hour and its `serving.json`
declares `interval_nominal_coverage`. Such intervals stay `uncalibrated`, with an
`UNCALIBRATED_INTERVALS` warning, until held-out coverage is validated (#20).

## Served artifacts

```text
<artifact_root>/<artifact_id>/     read-only once staged
  model/        artifact.json, model.json, source-sha256.json   (baselines.save_artifact)
  run.json      the packet's RunManifest; must name this artifact
  split.json    sha256 must equal run.split_manifest_sha256
  config.json   sha256 must equal run.config_sha256 (EvaluationConfig)
  serving.json  ServingSpec: input kind, feature policy, protocol hash
```

Loading refuses an artifact when any of these checks fails:

- The layout is incomplete or has extra files, or it contains a symlink.
- The receipt does not match the operator's pin.
- A content checksum or a packet hash does not match.
- A manifest fails strict schema validation.
- The baseline implementation does not match the code it was saved with.
- The model, evaluation, feature policy and feature order disagree.

Stage an artifact straight from a run's output:

```sh
uv run --extra api python -I -m hachi.api stage-artifact \
  --model RUN/outer-0-inner-0/models/<artifact_id> \
  --packet RUN/outer-0-inner-0/evaluations/<model_id> \
  --protocol RUN/protocol.json --artifact-root "$HACHI_ARTIFACT_ROOT"
```

## Apple Health imports

An Apple import has no PMData aggregates. A served hourly-feature artifact reaches it only when
its serving profile **explicitly admits** the source:

```json
"accepted_sources": [
  {
    "source": "apple_health",
    "feature_policy": {
      "metric": "heart_rate",
      "aggregation": "mean",
      "min_coverage": 0.5,
      "min_observed_count": 30,
      "availability_rule": "apple-hour-end-sealed-native-v1"
    },
    "rationale": "why this transfer is accepted"
  }
]
```

`stage-artifact --protocol … --admit-apple "<rationale>"` writes it, copying the model's own
metric, aggregation and gates. The admission must use #78's sealed Apple readiness rule; a
PMData rule is never stamped onto Apple bins.

An admitted Apple subject is fed by `hachi.data.apple_health.hourly.apple_hourly_features`
over the model's lookback, and then forecast as usual. Results carry a `DEVICE_SHIFT` warning
naming the evaluated dataset and the admission's rationale. **Admission is a transfer
decision, not validation.**

Without an admission, an Apple subject gets `unavailable` / `NO_ARTIFACT_FOR_TASK`, with a
requirement naming the dataset the served models were evaluated on.

Typical 5-minute Apple Watch HR fills about 12 minutes an hour, so it abstains at a 0.5
minute-density / 30-sample gate (`INSUFFICIENT_HISTORY`). Lowering those gates changes the
model's input semantics and belongs to the model owner.

The sealed-hour replay re-reads the import once per lookback hour, so its cost grows with
history length times lookback (see the #78 README). It runs inside the report job, never in
the request.

## GPU models (Chronos-2)

A Chronos-2 artifact from #10/#12 is staged like a baseline. `stage-artifact --protocol` sees the
`chronos-2-artifact-1` model and writes a serving spec with `requires_gpu: true` and
`interval_nominal_coverage: 0.8` (q0.1-q0.9). Only zero-shot, univariate artifacts whose context
equals the protocol lookback are served for now.

Each forecast is one GX10 job:

1. `build_request` (the evaluator's adapter) turns the causal hourly history into one context
   request. The request carries the context and horizon only: no subject id, cutoff or target.
2. Over SSH the API writes the request into the owner workspace and runs
   `scripts/gx10/gpu-run --owner <owner> --run-id api-chronos-<stamp>-<hex> -- <envs/<lock>/bin/python> -I src/hachi/models/chronos/inference.py …`
   from `HACHI_GX10_CHECKOUT`.
3. The API reads `inference.json` and `predictions.jsonl` back and refuses them unless:
   - the weights equal the pin's `weights_sha256` and the model revision matches;
   - the GX10's `inference.py` hashes like this checkout's;
   - the request and prediction checksums match the bytes sent and received;
   - exactly one prediction answers the request, with the requested horizon.
4. `estimates` (the evaluator's adapter) maps the quantiles to median and q0.1-q0.9 bounds.

Intervals are `uncalibrated` with an `UNCALIBRATED_INTERVALS` warning until #20 validates them.
Failures are errors, never guesses:

| Situation | Result |
|---|---|
| No GX10 configured | `GPU_UNAVAILABLE` |
| Host unreachable, or `gpu-run` exit 75 (GPU busy) | `GPU_UNAVAILABLE` |
| Job past `HACHI_GX10_TIMEOUT` | `INFERENCE_TIMEOUT` |
| Output fails any check above | `INFERENCE_FAILED` |

`GPU_UNAVAILABLE` and `INFERENCE_TIMEOUT` are transient, so an identical request runs again.

## Handoff check

With the API running, `handoff` requests every origin in a real evaluation packet over HTTP. It
compares each forecast with two references:

- the predictions the evaluator saved in the packet
- a fresh direct inference through `evaluate_forecast`

It compares the median and, when given, both bounds. `--tolerance` sets the largest
difference still counted as agreement (exact by default). `--no-direct` skips the second
reference, which saves GPU jobs for GPU models. It prints counts, differences and identities only:

```sh
uv run --extra api python -I -m hachi.api handoff \
  --base-url http://127.0.0.1:8716 --packet RUN/outer-0-inner-0/evaluations/<model_id>
```
