import json
from datetime import UTC, datetime
from pathlib import Path

from hachi.evaluation.folds import NestedFoldConfig, nested_participant_folds
from hachi.models.recovery import __main__ as runner
from hachi.models.recovery.clinical import Landmark
from hachi.models.recovery.cohorts import CMU
from hachi.models.recovery.protocol import CMUSplitProtocol
from hachi.models.recovery.survival import Observation, SurvivalModel

ROOT = Path(__file__).resolve().parents[3]


def test_runner_never_requests_test_outcomes_and_owns_development_export_counts(
    tmp_path, monkeypatch
):
    # All identifiers here are synthetic. Real test eligibility is deliberately unknown.
    folds = NestedFoldConfig(outer_folds=2, inner_folds=2, min_train_subjects=2, seed=42)
    plan = nested_participant_folds([f"synthetic-{n}" for n in range(12)], folds)
    active = [f for f in plan.folds if f.outer_fold == 0]
    sealed = set(active[0].test_subjects)
    development = set(active[0].train_subjects + active[0].validation_subjects)
    common = CMUSplitProtocol.model_validate_json(
        (ROOT / "configs/experiments/recovery/cmu-split.json").read_bytes()
    )
    common = common.model_copy(update={"folds": folds})
    document = json.loads((ROOT / "configs/experiments/recovery/cmu.json").read_bytes())
    document.update(minimum_followed_training_subjects=2, minimum_resolved_training_episodes=1)
    config = tmp_path / "protocol.json"
    config.write_text(json.dumps(document))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "uv.lock").write_text("synthetic-lock")
    monkeypatch.setattr(runner, "load_split", lambda *args: (common, plan))
    monkeypatch.setattr(
        runner, "dataset_snapshot_ref", lambda *args: common.compatible_snapshots[0]
    )
    monkeypatch.setattr(
        runner.subprocess,
        "check_output",
        lambda args, **kwargs: "0" * 40 if "rev-parse" in args else "",
    )
    requested = []

    def guarded_landmarks(snapshot, subjects, cohort):
        assert cohort == CMU
        assert set(subjects) <= development
        assert not set(subjects) & sealed
        requested.append(tuple(subjects))
        rows = [
            Landmark(
                Observation(s, f"{s}-episode", (3.0,), 3 if i == 0 else None, 3),
                datetime(2000, 1, 2, tzinfo=UTC),
                CMU.scale,
                False,
            )
            for i, s in enumerate(subjects)
        ]
        return rows, {"canonical_episodes": len(rows)}

    monkeypatch.setattr(runner, "landmarks", guarded_landmarks)
    monkeypatch.setattr(
        runner,
        "fit_survival",
        lambda rows, conditional, supported_days, **kwargs: SurvivalModel(
            (-2.0, 0.0, 0.0) if conditional else (-2.0,),
            (3.0,),
            (1.0,),
            conditional,
            supported_days,
            True,
            1,
        ),
    )
    output = tmp_path / "private"
    receipt = runner.run(Path("synthetic-snapshot"), config, output, repo)
    assert requested == [
        partition for f in active for partition in (f.train_subjects, f.validation_subjects)
    ]
    assert receipt["development_audit"] == {"canonical_episodes": len(development)}
    assert receipt["outer_test_outcomes_read_this_run"] is False
    assert receipt["outer_test_scored"] is False
    assert json.loads((output / "aggregate.json").read_bytes()) == receipt
    predictions = [json.loads(p.read_bytes()) for p in output.glob("inner-*/predictions.json")]
    assert receipt["private_export_audit"]["research_curves"] == sum(map(len, predictions))
