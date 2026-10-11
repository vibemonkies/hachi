"""Generated reader-boundary inputs; these tests are not real-cohort evidence."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hachi.contracts.tables import Aggregate
from hachi.data.pmdata import FeatureBin
from hachi.evaluation import pmdata_run


def protocol():
    path = Path(__file__).resolve().parents[2] / "configs/evaluation/pmdata-hourly-validation.json"
    return pmdata_run.PMDataProtocol.model_validate_json(path.read_bytes())


def test_run_boundary_keeps_test_sealed_and_artifacts_private(monkeypatch, tmp_path):
    pytest.importorskip("sklearn")
    from datetime import timedelta

    selected = protocol()
    subjects = [f"generated-{i}" for i in range(16)]
    bins = []
    for i, subject in enumerate(subjects):
        for hour in range(-96, 168):
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
                value=float(65 + i),
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
    output = tmp_path / "generated-run"
    summary = pmdata_run.run(tmp_path / "generated-snapshot", output, selected)
    assert summary["outer_test_sealed"] is True
    assert summary["validation_participants"] == 12
    assert summary["outer_test_participants"] == 4
    models = summary["models"]
    assert len(models) == 4 and all(m["artifact_replay_verified"] for m in models.values())
    splits = list(output.glob("outer-*/evaluations/*/split.json"))
    assert len(splits) == 12
    assert all(json.loads(p.read_text())["test_opened_at_utc"] is None for p in splits)
    assert all(
        p.stat().st_mode & 0o777 == (0o700 if p.is_dir() else 0o600) for p in output.rglob("*")
    )
    assert "subject_id" not in json.dumps(summary)


def test_protocol_refuses_mismatched_seed_and_model_target():
    selected = protocol()
    with pytest.raises(ValidationError, match="seed"):
        pmdata_run.PMDataProtocol.model_validate(
            {**selected.model_dump(), "tree": selected.tree.model_copy(update={"seed": 43})}
        )
    with pytest.raises(ValidationError, match="same metric"):
        pmdata_run.PMDataProtocol.model_validate(
            {
                **selected.model_dump(),
                "tree": selected.tree.model_copy(update={"metric": "hrv_sdnn"}),
            }
        )
