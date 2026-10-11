import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pytest

from hachi.data.clinical.config import Admission, AdmittedFile
from hachi.evaluation.folds import nested_participant_folds
from hachi.models.baselines.stanford import burden
from hachi.models.baselines.stanford.rest import HeartRatePoint, StepPoint
from hachi.models.baselines.stanford.source import NativeNights

CONFIG = Path(__file__).parents[3] / "configs/experiments/baselines/stanford-burden.json"


def protocol():
    return burden.BurdenProtocol.model_validate_json(CONFIG.read_bytes())


def test_abstentions_remain_in_coverage_and_zero_support_has_no_estimate():
    rows = [
        {
            "counts": {
                "observed_control_days": 10,
                "scored_control_days": 5,
                "alerted_control_days": 2,
                "alert_episodes_intersecting_controls": 1,
            }
        },
        {"counts": {"observed_control_days": 10}},
    ]
    result = burden.aggregate(rows, protocol())
    assert result["participants_with_scored_control_days"] == 1
    assert result["episodes_per30_scored_control_days"]["value"] == 6
    assert result["pooled_episodes_per30_all_observed_control_days"] == 1.5
    assert result["counts"]["observed_control_days"] == 20
    assert burden.aggregate(rows[1:], protocol())["episodes_per30_scored_control_days"] is None
    with pytest.raises(ValueError):
        burden.BurdenProtocol.model_validate({**protocol().model_dump(), "sensitivities": ["both"]})


def test_real_runner_seals_test_excludes_unknown_and_replays_causal_history(tmp_path, monkeypatch):
    config = protocol()
    subjects = [f"generated-{i}" for i in range(16)]
    plan = nested_participant_folds(subjects, config.folds)
    fold = plan.folds[0]
    control, unknown = fold.validation_subjects[:2]
    held_out = fold.test_subjects[0]
    days = [date(2020, 1, d) for d in (10, 11, 12, 14)]
    tables = {
        "subjects": pa.table({"subject_id": subjects}),
        "surveys": pa.Table.from_pylist(
            [{"subject_id": control, "local_date": date(2020, 1, 9), "state": "symptomatic"}]
        ),
        "onset_windows": pa.Table.from_pylist(
            [
                {"subject_id": s, "cutoff_day": d, "onset_24h": label}
                for s, label in (
                    (control, "negative"),
                    (unknown, "unknown"),
                    (held_out, "negative"),
                )
                for d in days
            ]
        ),
    }
    archive = tmp_path / "source.zip"
    archive.write_bytes(b"generated source admission")
    monkeypatch.setattr(burden, "verify", lambda _: {"ok": True})
    monkeypatch.setattr(burden, "dataset_snapshot_ref", lambda _: config.expected_snapshot)
    monkeypatch.setattr(burden, "load_manifest", lambda _: {"clock": config.rest.clock})
    monkeypatch.setattr(burden, "read_table", lambda _, name: tables[name])
    monkeypatch.setattr(burden, "phase1_members", lambda _: [])
    monkeypatch.setattr(
        burden,
        "registry_admission",
        lambda _: Admission(
            dataset_id=config.expected_snapshot.dataset_id,
            dataset_version=config.expected_snapshot.dataset_version,
            files={
                "COVID-19-Wearables.zip": AdmittedFile(
                    name="COVID-19-Wearables.zip",
                    bytes=archive.stat().st_size,
                    sha256=burden.sha(archive),
                )
            },
        ),
    )
    requested = []

    def native(_, members, subject, first, last):
        requested.append(subject)
        hr, steps = {}, {}
        day = first
        while day <= last:
            if day not in (date(2020, 1, 12), date(2020, 1, 13)):
                at = datetime.combine(day, datetime.min.time(), UTC)
                value = 100 if day in days else 60
                hr[day] = tuple(
                    HeartRatePoint(
                        at=at + timedelta(minutes=m, seconds=10),
                        bpm=value,
                    )
                    for m in range(30)
                )
                steps[day] = tuple(
                    StepPoint(
                        at=at + timedelta(minutes=m),
                        steps=0,
                    )
                    for m in range(31)
                )
            day += timedelta(days=1)
        return NativeNights(hr, steps, {"generated": 1}, ())

    monkeypatch.setattr(burden, "read_native_nights", native)
    output = tmp_path / "packet"
    result = burden.run(tmp_path, archive, output, config)
    assert requested == [control]
    counts = result["policies"]["both"]["counts"]
    assert counts["observed_control_days"] == 4
    assert counts["scored_control_days"] == 3
    assert counts["alerted_control_days"] == 3
    assert counts["alert_episodes_intersecting_controls"] == 2
    assert counts["abstained_missing_rest_measurement"] == 1
    assert result["replay"] == {"decisions_replayed": 12, "mismatches": 0}
    for path in output.glob("inner-*/split.json"):
        split = json.loads(path.read_bytes())
        assert split["test_opened_at_utc"] is None
        assert not set(split["validation_subjects"]) & set(split["test_subjects"])
    for path in output.glob("inner-*/run.json"):
        run = json.loads(path.read_bytes())
        assert run["artifact"] == result["artifact"]
        assert (path.parent / run["metrics_paths"][0]).is_file()
    for path in output.rglob("*"):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
