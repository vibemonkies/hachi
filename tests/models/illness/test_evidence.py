"""Evidence assembly must retain causal scope and disclose transformations."""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pytest

from hachi.models.illness.evidence import input_hashes, label_grid_check, packet_scores


def test_packet_inventory_and_score_roundtrip(tmp_path):
    from datetime import UTC, datetime

    from hachi.evaluation.serialization import document_bytes
    from hachi.models.illness.data import Window
    from hachi.models.illness.metrics import Score

    expected = []
    for i in range(3):
        row = Score(
            Window(
                f"synthetic-{i}",
                datetime(2020, 1, 1, tzinfo=UTC),
                24,
                False,
                None,
                None,
                None,
                (0.0, None),
            ),
            0.2,
            0.3,
        )
        packet = tmp_path / f"inner-{i}-24h-tree"
        packet.mkdir()
        (packet / "predictions.json").write_bytes(document_bytes([row]))
        expected.append(row)
    assert packet_scores(tmp_path, 24, "tree") == expected
    before = input_hashes(tmp_path)
    assert len(before) == 3
    path = tmp_path / "inner-0-24h-tree/predictions.json"
    assert before[str(path.relative_to(tmp_path))] == hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_bytes(b"[]\n")
    assert input_hashes(tmp_path) != before


def test_label_recheck_uses_only_development_and_rejects_mismatch(monkeypatch):
    import hachi.models.illness.evidence as evidence

    fold = SimpleNamespace(
        outer_fold=0, validation_subjects=("synthetic-dev",), test_subjects=("synthetic-sealed",)
    )
    monkeypatch.setattr(evidence, "clinical_fold_plan", lambda *args: SimpleNamespace(folds=[fold]))
    rows = [
        {
            "subject_id": "synthetic-dev",
            "cutoff_utc": "synthetic-coordinate",
            **{f"onset_{h}h": "negative" for h in (24, 48, 72)},
            **{f"onset_episode_{h}h": None for h in (24, 48, 72)},
        }
    ]

    def guarded(snapshot, name=None, subjects=None, **kwargs):
        assert tuple(subjects) == fold.validation_subjects
        return pa.Table.from_pylist(rows)

    monkeypatch.setattr(evidence, "read_table", guarded)
    monkeypatch.setattr(evidence, "onset_labels", guarded)
    protocol = SimpleNamespace(active_outer_fold=0)
    result = label_grid_check(Path("synthetic"), protocol)
    assert result == {
        "development_cutoffs": 1,
        "onset_label_episode_comparisons": 6,
        "mismatches": 0,
        "outer_test_read": False,
    }
    wrong = [{**rows[0], "onset_24h": "positive"}]
    monkeypatch.setattr(
        evidence, "onset_labels", lambda *args, **kwargs: pa.Table.from_pylist(wrong)
    )
    with pytest.raises(ValueError, match="grid differs"):
        label_grid_check(Path("synthetic"), protocol)


def test_replay_keeps_virtual_environment_executable_path(tmp_path, monkeypatch):
    import io
    import json
    import tarfile

    import hachi.models.illness.evidence as evidence

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w"):
        pass
    monkeypatch.setattr(evidence.subprocess, "check_output", lambda *a, **k: buffer.getvalue())
    underlying = tmp_path / "system-python"
    underlying.touch()
    virtual_python = tmp_path / "venv-python"
    virtual_python.symlink_to(underlying)

    def worker(args, **kwargs):
        assert args[0] == str(virtual_python)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"decision_mismatches": 0}))

    monkeypatch.setattr(evidence.subprocess, "run", worker)
    assert evidence.replay([], "a" * 40, virtual_python) == {"decision_mismatches": 0}


def test_saved_scored_rows_must_belong_to_exact_validation_cohort(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    import hachi.models.illness.evidence as evidence
    from hachi.evaluation.serialization import document_bytes
    from hachi.models.illness.data import Window
    from hachi.models.illness.metrics import Score

    expected = Window(
        "synthetic-validation",
        datetime(2020, 1, 1, tzinfo=UTC),
        24,
        False,
        None,
        None,
        None,
        (1.0, 1.0, 0.0, 0.0),
    )
    monkeypatch.setattr(evidence, "at_risk_windows", lambda *a: ([expected], {}))
    partitions = {
        "train_subjects": ["synthetic-train"],
        "validation_subjects": ["synthetic-validation"],
        "test_subjects": ["synthetic-sealed"],
    }
    fold = SimpleNamespace(
        outer_fold=0,
        inner_fold=0,
        validation_subjects=partitions["validation_subjects"],
        partitions=lambda: partitions,
    )
    plan = SimpleNamespace(folds=[fold])
    protocol = SimpleNamespace(active_outer_fold=0, horizons_hours=[24], candidate_order=["tree"])
    packet = tmp_path / "inner-0-24h-tree"
    packet.mkdir()
    (packet / "split.json").write_bytes(document_bytes({**partitions, "test_opened_at_utc": None}))
    (packet / "predictions.json").write_bytes(document_bytes([Score(expected, 0.2, 0.3)]))
    evidence.validate_predictions(tmp_path, tmp_path, plan, protocol)
    from dataclasses import replace

    sealed = replace(expected, subject_id="synthetic-sealed")
    (packet / "predictions.json").write_bytes(document_bytes([Score(sealed, 0.2, 0.3)]))
    with pytest.raises(ValueError, match="validation cohort"):
        evidence.validate_predictions(tmp_path, tmp_path, plan, protocol)


def test_render_does_not_claim_unchecked_previous_runs():
    import json

    from hachi.models.illness.evidence import render
    from hachi.models.illness.protocol import load_protocol

    report = json.loads(Path("reports/models/illness/phase1.json").read_bytes())
    report["protocol_document"] = load_protocol(
        Path("configs/experiments/illness/phase1.toml")
    ).model_dump(mode="json")
    report["base_replay"] = json.loads(Path("reports/models/illness/base-replay.json").read_bytes())
    report["past_survey_distribution_by_label"] = {}
    report["report_provenance"] = {"producing_commit": "a" * 40, "source_only_rerun_comparison": {}}
    rendered = render(report)
    assert "not checked; no prior packets supplied" in rendered
    assert "722f51a after" not in rendered
    assert "-001" not in rendered


def test_report_render_matches_canonical_json_order():
    import json

    from hachi.models.illness.evidence import render

    report = json.loads(Path("reports/models/illness/phase1.json").read_bytes())
    reordered = dict(reversed(list(report.items())))
    reordered["past_survey_distribution_by_label"] = {
        h: dict(reversed(list(groups.items())))
        for h, groups in reversed(list(report["past_survey_distribution_by_label"].items()))
    }
    assert render(reordered) == render(report)
    assert render(report) == Path("reports/models/illness/phase1.md").read_text()
