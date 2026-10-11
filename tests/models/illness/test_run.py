"""Exercise the actual private packet path on a synthetic cohort, with outer test sealed."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from hachi.evaluation.clinical_protocol import ClinicalProtocol
from hachi.evaluation.folds import nested_participant_folds
from hachi.evaluation.serialization import document_sha256
from hachi.models.illness import data
from hachi.models.illness.data import FeatureSet
from hachi.models.illness.protocol import load_protocol
from hachi.models.illness.run import run

pytest.importorskip("sklearn", reason="illness runner requires the baselines extra")

PROTOCOL = load_protocol(Path("configs/experiments/illness/phase1.toml")).model_copy(
    update={"bootstrap_replicates": 100}
)


@pytest.fixture
def snapshot(tmp_path):
    path = tmp_path / "synthetic-snapshot"
    path.mkdir()
    subjects = [f"synthetic-{i}" for i in range(24)]
    pq.write_table(
        pa.Table.from_pylist([{"subject_id": s} for s in subjects]), path / "subjects.parquet"
    )
    manifest = {
        "dataset_snapshot": {
            "dataset_id": PROTOCOL.dataset_id,
            "dataset_version": "2020-nbe",
            "snapshot_sha256": PROTOCOL.snapshot_sha256,
        },
        "clock": PROTOCOL.clock,
        "definitions": {"definitions_version": "outcomes-1"},
    }
    (path / "manifest.json").write_text(json.dumps(manifest))
    episodes, surveys, rows = [], [], []
    for sid in subjects:
        for k in range(20):
            day = date(2020, 1, 1) + timedelta(days=k)
            positive = k % 4 == 0
            eid = f"{sid}-event-{k}" if positive else None
            if positive:
                episodes.append(
                    {
                        "subject_id": sid,
                        "episode_id": eid,
                        "onset_first_day": day,
                        "onset_last_day": day,
                    }
                )
            surveys.append({"subject_id": sid, "local_date": day, "state": "symptom_free"})
            row = {"subject_id": sid, "cutoff_utc": datetime.combine(day, datetime.min.time(), UTC)}
            for h in [24, 48, 72]:
                row[f"onset_{h}h"] = "positive" if positive else "negative"
                row[f"onset_episode_{h}h"] = eid
            rows.append(row)
    for name, records in [("episodes", episodes), ("surveys", surveys), ("onset_windows", rows)]:
        pq.write_table(pa.Table.from_pylist(records), path / f"{name}.parquet")
    return path, subjects


def clinical(plan):
    return ClinicalProtocol(
        compatible_snapshots=[
            {
                "dataset_id": PROTOCOL.dataset_id,
                "dataset_version": "2020-nbe",
                "snapshot_sha256": PROTOCOL.snapshot_sha256,
            }
        ],
        clock=PROTOCOL.clock,
        roster="all_subjects_before_task_eligibility",
        folds=PROTOCOL.folds,
        active_outer_fold=0,
        nested_plan_sha256=document_sha256(plan),
        split_created_at_utc=datetime(2026, 10, 11, 11, 45, tzinfo=UTC),
    )


def clean_run(monkeypatch):
    monkeypatch.setattr("hachi.models.illness.run.verify", lambda snapshot: {"ok": True})
    monkeypatch.setattr("hachi.evaluation.clinical_protocol.verify", lambda snapshot: {"ok": True})
    monkeypatch.setattr(
        "hachi.models.illness.run.subprocess.check_output",
        lambda args, **kwargs: "" if "--porcelain" in args else "a" * 40,
    )


def test_actual_runner_private_packets_canonical_manifests_and_sealed_test(
    snapshot, tmp_path, monkeypatch
):
    path, subjects = snapshot
    plan = nested_participant_folds(subjects, PROTOCOL.folds)
    outer_test = set(plan.folds[0].test_subjects)
    original = data.read_table
    seen = []

    def guarded(snapshot, name, selected=None):
        if name != "subjects":
            assert selected is not None and not outer_test & set(selected)
            seen.append(name)
        return original(snapshot, name, selected)

    monkeypatch.setattr(data, "read_table", guarded)
    clean_run(monkeypatch)
    summary = run(
        path,
        tmp_path / "packet",
        PROTOCOL,
        clinical=clinical(plan),
    )
    assert len(summary["fold_evidence"]) == 27
    assert summary["outer_test_status"] == "sealed"
    assert set(seen) == {"episodes", "surveys", "onset_windows"}
    for entry in summary["fold_evidence"]:
        assert entry["status"] == "fitted"
        assert entry["replay_max_probability_difference"] < 1e-12
    for packet in (tmp_path / "packet").glob("inner-*"):
        manifest = json.loads((packet / "run.json").read_text())
        assert manifest["config_sha256"] == document_sha256(
            json.loads((packet / "config.json").read_text())
        )
        assert manifest["split_manifest_sha256"] == document_sha256(
            json.loads((packet / "split.json").read_text())
        )
        split = json.loads((packet / "split.json").read_text())
        assert split["test_opened_at_utc"] is None
        assert set(split["test_subjects"]) == outer_test
        assert json.loads((packet / "serving.json").read_text())["status"] == "unavailable"
        assert (packet / "predictions.json").stat().st_mode & 0o777 == 0o600


def test_at_risk_unknown_controls_and_exclusions_never_become_negative(snapshot):
    path, subjects = snapshot
    table = pq.read_table(path / "onset_windows.parquet").to_pylist()
    for row in table:
        if row["subject_id"] == subjects[0]:
            for h in [24, 48, 72]:
                row[f"onset_{h}h"] = "unknown_no_survey"
    pq.write_table(pa.Table.from_pylist(table), path / "onset_windows.parquet")
    rows, counts = data.at_risk_windows(path, subjects[:2], PROTOCOL)
    assert {r.subject_id for r in rows} == {subjects[1]}
    assert counts["24h:unknown_no_survey"] == 20


def test_external_fit_on_calibration_subject_is_rejected(snapshot, tmp_path, monkeypatch):
    path, subjects = snapshot
    plan = nested_participant_folds(subjects, PROTOCOL.folds)
    from hachi.models.illness.training import calibration_partition

    _, calibration = calibration_partition(plan.folds[0].train_subjects, PROTOCOL)
    features = FeatureSet(
        feature_names=("external",),
        provenance_sha256="d" * 64,
        fit_subjects=(calibration[0],),
        clock="floating_local_shifted",
        points=(),
    )
    clean_run(monkeypatch)
    with pytest.raises(ValueError, match="external feature fitting"):
        run(
            path,
            tmp_path / "rejected",
            PROTOCOL,
            clinical=clinical(plan),
            external_by_inner={0: features, 1: features, 2: features},
        )


def test_partial_external_fold_candidates_do_not_pool_incompatible_features(
    snapshot, tmp_path, monkeypatch
):
    path, subjects = snapshot
    plan = nested_participant_folds(subjects, PROTOCOL.folds)
    clean_run(monkeypatch)
    features = FeatureSet(
        feature_names=("external",),
        provenance_sha256="d" * 64,
        fit_subjects=(),
        clock="floating_local_shifted",
        points=(),
    )
    with pytest.raises(ValueError, match="every active inner fold"):
        run(
            path,
            tmp_path / "rejected",
            PROTOCOL,
            clinical=clinical(plan),
            external_by_inner={0: features},
        )


def test_pretrained_support_gate_prevents_any_fit_scores_or_selection(
    snapshot, tmp_path, monkeypatch
):
    from hachi.models.illness.data import FeaturePoint
    from hachi.models.illness.pretrained_protocol import (
        load_pretrained_protocol,
        representation_feature_names,
    )

    path, subjects = snapshot
    plan = nested_participant_folds(subjects, PROTOCOL.folds)
    shared = clinical(plan)
    frozen = load_pretrained_protocol(Path("configs/experiments/illness/pretrained.json"))
    # Synthetic policy identity only; the clinical production document remains unchanged.
    comparison = frozen.model_copy(
        update={
            "task_protocol": frozen.task_protocol.model_copy(update={"sha256": PROTOCOL.sha256}),
            "clinical_protocol": frozen.clinical_protocol.model_copy(
                update={"sha256": document_sha256(shared)}
            ),
        }
    )
    clean_run(monkeypatch)

    def forbidden_fit(*args, **kwargs):
        pytest.fail("unsupported calibration reached classifier fitting")

    monkeypatch.setattr("hachi.models.illness.run.fit", forbidden_fit)
    external, support = {}, {}
    for fold in plan.folds:
        if fold.outer_fold != 0:
            continue
        rows, _ = data.at_risk_windows(
            path, fold.train_subjects + fold.validation_subjects, PROTOCOL
        )
        keys = {(r.subject_id, r.cutoff) for r in rows}
        external[fold.inner_fold] = FeatureSet(
            feature_names=representation_feature_names(frozen.representations[-1]),
            provenance_sha256="e" * 64,
            fit_subjects=(),
            clock="floating_local_shifted",
            points=tuple(
                FeaturePoint(subject_id=s, at=c, available_at=c, values=(1.0,) * 770)
                for s, c in sorted(keys)
            ),
        )
        support[fold.inner_fold] = frozenset(keys)
    summary = run(
        path,
        tmp_path / "unsupported",
        PROTOCOL,
        clinical=shared,
        external_by_inner=external,
        feature_family="chronos_hr",
        comparison=comparison,
        supported_by_inner=support,
    )
    assert all(
        e["status"] == "insufficient_context_supported_calibration_participants"
        and e["scored_validation_windows"] == 0
        for e in summary["fold_evidence"]
    )
    assert not list((tmp_path / "unsupported").glob("inner-*/predictions.json"))
    assert all(
        s["development_candidate"] is None and s["status"] == "descriptive_only_no_selection"
        for s in summary["selection"].values()
    )
    assert summary["pretrained_protocol_sha256"] == document_sha256(comparison)
    wrong_schema = {
        inner: features.model_copy(update={"feature_names": ("wrong_width_and_name",)})
        for inner, features in external.items()
    }
    rejected = tmp_path / "wrong-schema"
    with pytest.raises(ValueError, match="schema differs from frozen"):
        run(
            path,
            rejected,
            PROTOCOL,
            clinical=shared,
            external_by_inner=wrong_schema,
            feature_family="chronos_hr",
            comparison=comparison,
            supported_by_inner=support,
        )
    assert not rejected.exists()
