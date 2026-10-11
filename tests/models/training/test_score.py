"""Generated reader-boundary inputs through export → fake GX10 → score; not real evidence."""

import json
import math
from datetime import UTC, datetime, timedelta

import pytest

from hachi.contracts.tables import Aggregate
from hachi.data.pmdata import FeatureBin
from hachi.evaluation import pmdata_run
from hachi.evaluation.serialization import document_sha256
from hachi.models.chronos.inference import (
    embed_rows,
    forecast_rows,
    read_requests,
    write_run,
)
from hachi.models.training import pmdata as training_pmdata
from hachi.models.training.pmdata import export, load_experiment, prepare
from hachi.models.training.score import run_score

HOUR = timedelta(hours=1)
START = datetime(2019, 12, 16, tzinfo=UTC)
END = datetime(2020, 1, 8, tzinfo=UTC)
LEVELS = (0.01, 0.05, *(round(0.05 * i, 2) for i in range(2, 19)), 0.95, 0.99)


def bins(subjects):
    rows = []
    hours = int((END - START) / HOUR)
    for i, subject in enumerate(subjects):
        for h in range(hours):
            if (h + i) % 13 == 0:
                continue  # generated gaps stay missing
            start = START + h * HOUR
            for metric, value in (
                ("heart_rate", round(60 + i + 7 * math.sin(2 * math.pi * start.hour / 24), 3)),
                ("steps", float((h * 37 + i * 11) % 400)),
            ):
                row = Aggregate(
                    dataset_id="pmdata",
                    subject_id=subject,
                    metric=metric,
                    unit="bpm" if metric == "heart_rate" else "count",
                    resolution="hour",
                    interval_start_utc=start,
                    interval_end_utc=start + HOUR,
                    local_date=None,
                    tz_name="Europe/Oslo",
                    aggregation="mean" if metric == "heart_rate" else "sum",
                    value=value,
                    null_reason=None,
                    observed_count=60,
                    coverage=1.0,
                    source_ids=["generated-device"],
                    pipeline_version="generated-1",
                )
                rows.append(FeatureBin(row, row.interval_end_utc))
    return rows


def fake_gx10(export_dir, root, experiment):
    pin = experiment.chronos.chronos.model
    zeroshot, embed = root / "zeroshot", root / "embed"
    zeroshot.mkdir()
    embed.mkdir()
    requests = read_requests(export_dir / "forecast-requests.jsonl")

    def forecaster(items, length):
        output = []
        for item in items:
            last = next(v for v in reversed(item.context) if v is not None)
            nudge = 0.5 if item.past_covariates else 0.0
            output.append([[last + nudge + 8 * (q - 0.5) for q in LEVELS] for _ in range(length)])
        return output

    rows, _, crossed = forecast_rows(requests, forecaster, batch_size=128, levels=LEVELS)
    memory = {
        "peak_process_rss_kib": 1024,
        "peak_cuda_allocated_bytes_batched": 2048,
        "peak_cuda_allocated_bytes": 2048,
    }
    timing = {"single_request_seconds_p95": 0.02, "single_request_seconds_p50": 0.01}
    details = {
        "model": {"model_id": pin.model_id, "revision": pin.revision},
        "weights_sha256": pin.weights_sha256,
        "timing": timing,
        "memory": memory,
        "environment": {"gpu": "generated"},
    }
    write_run(
        zeroshot, export_dir / "forecast-requests.jsonl", requests, rows, LEVELS, crossed, details
    )
    embeds = read_requests(export_dir / "embed-requests.jsonl")

    def embedder(items):
        out = []
        for item in items:
            values = [v for v in item.context if v is not None]
            mean = sum(values) / len(values)
            out.append(
                ([values[-1] - mean, max(values) - mean, min(values) - mean, 1.0], mean, 1.0)
            )
        return out

    write_run(
        embed,
        export_dir / "embed-requests.jsonl",
        embeds,
        embed_rows(embeds, embedder, batch_size=256),
        LEVELS,
        0,
        details,
        kind="embed",
    )
    return zeroshot, embed


def test_export_and_score_select_on_identical_origins_without_identifiers(monkeypatch, tmp_path):
    pytest.importorskip("sklearn", reason="comparators and stacking need the baselines extra")
    experiment = load_experiment()
    subjects = [f"generated-{i:02d}" for i in range(12)]
    generated = bins(subjects)
    monkeypatch.setattr(pmdata_run, "verify", lambda _: {"ok": True})
    monkeypatch.setattr(
        pmdata_run, "dataset_snapshot_ref", lambda _: experiment.protocol.expected_snapshot
    )
    monkeypatch.setattr(pmdata_run, "load_manifest", lambda _: {"subjects": subjects})

    def aggregates(_snapshot, _resolution, *, metrics=None, **_):
        return iter([b for b in generated if metrics is None or b.aggregate.metric in metrics])

    monkeypatch.setattr(pmdata_run, "iter_aggregates", aggregates)
    monkeypatch.setattr(training_pmdata, "iter_aggregates", aggregates)
    inputs = prepare(tmp_path / "snapshot", experiment)
    assert len(inputs.meta) == 3 and all(len(group) == 4 for group in inputs.meta)
    for fold, group in zip(inputs.folds, inputs.meta, strict=True):
        for manifest in group:
            assert not set(manifest.train_subjects) & set(fold.validation_subjects)
            assert not set(manifest.train_subjects) & set(fold.test_subjects)

    exported = export(inputs, tmp_path / "export")
    assert exported["requests"]["forecast"] > 0 and exported["requests"]["embed"] > 0
    zeroshot, embed = fake_gx10(tmp_path / "export", tmp_path, experiment)

    def measure(name, *_):
        return {"latency_p95_seconds": 0.001, "peak_memory_bytes": 1000, "where": "generated"}

    summary = run_score(
        inputs,
        snapshot=tmp_path / "snapshot",
        export_dir=tmp_path / "export",
        zeroshot_dir=zeroshot,
        embed_dir=embed,
        finetune_runs={},
        output=tmp_path / "score",
        measure=measure,
    )
    order = experiment.rule.candidate_order
    assert summary["selection"]["selected"] in order
    statuses = {s["candidate"]: s["status"] for s in summary["selection"]["steps"]}
    assert statuses["chronos-2-finetuned"] == "not_available"
    assert all(
        s["packets"] for s in summary["selection"]["steps"] if s["status"] != "not_available"
    )
    assert {a["ablation"].split(":")[0] for a in summary["ablations"]} >= {
        "channel",
        "context",
        "representation",
        "personalization",
        "combination",
    }
    support = summary["ensemble_support"]["inner-0"]
    assert support["complete_labelled_fit_points"] > 0
    assert all(abs(sum(w.values()) - 1) < 1e-6 for w in support["weights"].values())
    point = summary["candidates"]["hourly-last-valid-v1"]
    assert point["interval_coverage"] is not None  # residual intervals from meta points
    text = json.dumps(summary)
    assert "generated-" not in text and "subject_id" not in text
    assert summary["outer_test_sealed"] is True
    evaluations = list((tmp_path / "score" / "candidates").glob("*/inner-*/split.json"))
    assert all(json.loads(p.read_text())["test_opened_at_utc"] is None for p in evaluations)
    assert len({document_sha256(m) for m in inputs.splits}) == 3
