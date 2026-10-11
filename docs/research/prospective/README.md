# Private prospective journal preparation (#25)

This is a useful **synthetic-only software preparation**, not delivery of the real prospective study. #25 remains open. [PROTOCOL.md](PROTOCOL.md) freezes the preparation design, measured outcomes, analysis/versioning and the external prerequisites. The supported success path is canonical next-local-day physiology forecasts; clinical successful results and real mode are refused. Unavailable/error results are retained without pretending they can be scored.

No shared schema, lockfile, API, storage, UI or GPU environment changes. Canonical `ReportRequest`, `ReportResult`, `ArtifactRef`, `DatasetSnapshotRef`, `Aggregate` and `evaluation.serialization` are reused. #21's retrospective sealed-case lifecycle is a separate consumer; this journal does not copy it or assert its custody. #20 selection/calibration hashes reference delivered decisions, never grant test-opening permission.

## Run generated proof

From this exact checkout, in its isolated `.venv`:

```sh
uv sync --locked
uv run --locked pytest tests/evaluation/prospective
uv run --locked python -m hachi.evaluation.prospective generated-proof
```

The command runs the actual private disk append/verify functions in an external temporary directory using invented data and an explicitly **simulated future clock**, emits aggregate proof only and removes its own generated temporary files. It verifies three chained receipts and demonstrates early-follow-up, stale-head, input-tamper, prediction-backfill, real-mode, duplicate-follow-up and receipt-tamper refusals. Tests additionally exercise competing writers, exact request/artifact/snapshot/timezone/window bindings, suffix removal, chain rehashing against a retained pin, unsafe files, missing/null measurements and sanitized CLI errors. This does not run a real model, wait for future outcomes, establish custody or prove scientific performance.

## Private caller

All record/input/output paths must remain in approved private storage, outside any Git checkout. Canonical absolute paths must not contain symlinks (on macOS use `/private/tmp`, not the `/tmp` alias). The parent directory must exist; registration exclusively creates a 0700 journal. Receipt files are exclusive 0600 files. The journal never changes permissions on existing files or rewrites a receipt. Interrupted/invalid appends leave a refused journal; do not silently remove a partial receipt and resume it as intact evidence. Keep the last **returned** head digest in separately controlled storage before the next step.

```python
from hachi.evaluation.prospective import Journal, Prediction

registration = Journal.create(private_path, protocol, analysis_plan=plan_bytes)
journal = Journal(private_path)
# Both documents are already validated canonical request/result values.
saved = journal.predict(
    Prediction(request=request, result=result, dataset_snapshot=snapshot,
               input_sha256=input_digest, protocol_sha256=protocol_digest,
               system_sha256=system_digest,
               window_start_utc=start, window_end_utc=end),
    expected_head=registration.sha256, input_document=exact_feature_bytes,
)
# After the whole measured day: canonical aggregate bytes must equal captured rows.
final = journal.follow_up(follow_up, expected_head=saved.sha256,
                          outcome_document=canonical_aggregate_bytes)
journal.verify(final.sha256)
```

CLI equivalents read private JSON and print only receipt hashes/counts. There is no user-supplied clock option or real-study enable switch:

```sh
uv run --locked python -m hachi.evaluation.prospective register PRIVATE_JOURNAL PRIVATE_PROTOCOL_JSON ANALYSIS_PLAN
uv run --locked python -m hachi.evaluation.prospective predict PRIVATE_JOURNAL PRIVATE_PREDICTION_JSON PRIVATE_INPUT --expected-head RETAINED_HEAD
uv run --locked python -m hachi.evaluation.prospective follow-up PRIVATE_JOURNAL PRIVATE_FOLLOW_UP_JSON PRIVATE_AGGREGATES --expected-head RETAINED_HEAD
uv run --locked python -m hachi.evaluation.prospective verify PRIVATE_JOURNAL --expected-head RETAINED_HEAD
```

Plan and input checksums cover exact bytes. Aggregate document bytes use `document_bytes(follow_up.aggregates)`; keep input snapshot and outcome snapshot separate because follow-up extends the data version. The registry freezes the supplied plan digest. It does not interpret that plan, authenticate provenance, verify a real input's consent or prove that someone labeled real data honestly: the synthetic mode check is procedural. No raw document, identifier, participant prediction or weight is emitted by the CLI. Do not put private input/result/receipt files, head pins or outcome rows in Git, GitHub, mail or terminal output.

The summary output is not a metric report. Future approved scoring must retain missingness, abstentions, drift and all negative results under the frozen protocol; this preparation does not provide clinical calibration or alert statistics.
