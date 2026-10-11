"""Generated reader-boundary inputs through export → fake GX10 → score; not real evidence."""

import json
import math
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from hachi.contracts.tables import Aggregate
from hachi.data.pmdata import FeatureBin
from hachi.evaluation import pmdata_run
from hachi.evaluation.pmdata_run import PMDataProtocol
from hachi.evaluation.serialization import document_sha256
from hachi.models.chronos import pmdata
from hachi.models.chronos.inference import forecast_rows, read_requests, write_run

from .conftest import LEVELS

ROOT = Path(__file__).resolve().parents[3]


def protocol() -> PMDataProtocol:
    path = ROOT / "configs/evaluation/pmdata-hourly-validation.json"
    return PMDataProtocol.model_validate_json(path.read_bytes())


def config() -> pmdata.ChronosPMDataConfig:
    path = ROOT / "configs/models/chronos/pmdata-hourly-hr.json"
    return pmdata.ChronosPMDataConfig.model_validate_json(path.read_bytes())


def test_committed_config_is_bound_to_the_committed_protocol_and_gx10_pin():
    selected, bound = protocol(), config()
    pmdata.check_binding(selected, bound)
    pin = json.loads((ROOT / "infra/gx10/model.json").read_text())
    assert bound.chronos.model.revision == pin["revision"]
    assert bound.chronos.model.weights_sha256 == pin["weights_sha256"]
    lock = ROOT / "infra/gx10/requirements.lock"
    assert bound.chronos.model.runtime_lock_sha256 == pmdata.file_sha256(lock)
    changed = selected.model_copy(update={"lookback_hours": 72})
    with pytest.raises(ValueError, match="different protocol"):
        pmdata.check_binding(changed, bound)
    evaluation = pmdata.chronos_evaluation(selected, bound)
    assert evaluation.model_dump(exclude={"pretrained_cohort_overlap", "overlap_note"}) == (
        selected.evaluation.model_dump(exclude={"pretrained_cohort_overlap", "overlap_note"})
    )
    with pytest.raises(ValidationError):
        pmdata.ChronosPMDataConfig.model_validate(
            {**bound.model_dump(), "pretrained_cohort_overlap": "not_applicable"}
        )


def fake_forecaster(contexts, length):
    output = []
    for context in contexts:
        last = next(v for v in reversed(context.context) if v is not None)
        output.append([[last + 10 * (q - 0.5) for q in LEVELS] for _ in range(length)])
    return output


def test_export_then_score_keeps_test_sealed_and_summary_identifier_free(monkeypatch, tmp_path):
    pytest.importorskip("sklearn")
    selected, bound = protocol(), config()
    subjects = [f"generated-{i}" for i in range(16)]
    bins = []
    for i, subject in enumerate(subjects):
        for hour in range(-120, 168):
            if (hour + i) % 11 == 0:
                continue  # generated gaps stay missing
            start = selected.evaluation_window.start_utc + timedelta(hours=hour)
            row = Aggregate(
                dataset_id="pmdata",
                subject_id=subject,
                metric="heart_rate",
                unit="bpm",
                resolution="hour",
                interval_start_utc=start,
                interval_end_utc=start + timedelta(hours=1),
                local_date=None,
                tz_name="Europe/Oslo",
                aggregation="mean",
                value=round(60 + i + 6 * math.sin(2 * math.pi * start.hour / 24), 3),
                null_reason=None,
                observed_count=120,
                coverage=1.0,
                source_ids=["generated-device"],
                pipeline_version="generated-1",
            )
            bins.append(FeatureBin(row, row.interval_end_utc))
    monkeypatch.setattr(pmdata_run, "verify", lambda _: {"ok": True})
    monkeypatch.setattr(pmdata_run, "dataset_snapshot_ref", lambda _: selected.expected_snapshot)
    monkeypatch.setattr(pmdata_run, "load_manifest", lambda _: {"subjects": subjects})
    monkeypatch.setattr(pmdata_run, "iter_aggregates", lambda *args, **kwargs: iter(bins))
    inputs = pmdata.prepare(tmp_path / "snapshot", selected, bound)
    assert len(inputs.splits) == 3
    assert all(s.test_opened_at_utc is None for s in inputs.splits)

    exported = pmdata.export(inputs, tmp_path / "export")
    assert exported["labels_passed_to_harness"] is False
    assert exported["requests"] > 0

    run = tmp_path / "gx10"
    run.mkdir()
    requests_path = tmp_path / "export" / "requests.jsonl"
    requests = read_requests(requests_path)
    rows, _, crossed = forecast_rows(requests, fake_forecaster, batch_size=64, levels=LEVELS)
    pin = bound.chronos.model
    write_run(
        run,
        requests_path,
        requests,
        rows,
        LEVELS,
        crossed,
        {
            "model": {"model_id": pin.model_id, "revision": pin.revision},
            "weights_sha256": pin.weights_sha256,
            "timing": {"single_request_seconds_p50": 0.01},
            "memory": {"peak_cuda_allocated_bytes_batched": 1},
            "environment": {"gpu": "generated"},
        },
    )
    summary = pmdata.score(inputs, tmp_path / "export", run, tmp_path / "score")
    assert summary["outer_test_sealed"] is True
    assert summary["validation_participants"] == 12
    assert set(summary["models"]) == {
        "chronos-2-zero-shot",
        "hourly-last-valid-v1",
        "utc-seasonal-naive-v1",
        "train-population-mean-v1",
        "causal-hourly-tree-v1",
    }
    assert len(summary["paired_vs_comparators"]) == 4
    text = json.dumps(summary)
    assert "generated-" not in text and "subject_id" not in text
    packets = list((tmp_path / "score").glob("outer-0-inner-*/vs-*/comparison.json"))
    assert len(packets) == 12
    assert all(
        p.stat().st_mode & 0o777 == (0o700 if p.is_dir() else 0o600)
        for p in (tmp_path / "score").rglob("*")
    )
    cost = summary["cost"]["comparators_cpu"]
    assert all(c["fit_seconds"]["calls"] == 3 for c in cost.values())
    assert all(c["predict_peak_traced_bytes"] > 0 for c in cost.values())


def test_score_refuses_an_export_from_a_different_split(monkeypatch, tmp_path):
    selected, bound = protocol(), config()
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "export.json").write_text(
        json.dumps(
            {
                "protocol_sha256": document_sha256(selected),
                "config_sha256": "0" * 64,
                "nested_plan_sha256": "0" * 64,
                "folds": [],
            }
        )
    )
    inputs = pmdata.Inputs(selected, bound, selected.evaluation, None, (), (), None, ())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="config_sha256"):
        pmdata.score(inputs, export_dir, tmp_path / "gx10", tmp_path / "score")
