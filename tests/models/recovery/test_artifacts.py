import json

import pytest

from hachi.models.recovery.artifacts import RecoveryArtifact, load_artifact, save_artifact
from hachi.models.recovery.cohorts import CMU
from hachi.models.recovery.survival import SurvivalModel


def test_private_artifact_parity_abstention_and_tamper(tmp_path):
    artifact = RecoveryArtifact(SurvivalModel((-2.0,), (0.0,) * 3, (1.0,) * 3, False, 7, True, 1))
    root = tmp_path / "model"
    ref = save_artifact(root, artifact, "synthetic-recovery")
    loaded = load_artifact(root, ref)
    assert loaded == artifact
    assert loaded.predict("synthetic-episode", (1, 2, 3)) is None
    payload = loaded.research_payload("synthetic-episode", (1, 2, 3))
    assert payload.survival[0].probability_still_symptomatic == 1
    assert payload.supported_follow_up_days == 7
    assert payload.median_days_after_as_of <= 7
    for p in root.iterdir():
        assert p.stat().st_mode & 0o777 == 0o600
    p = root / "model.json"
    document = json.loads(p.read_text())
    document["model"]["supported_days"] = 99
    p.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="checksum"):
        load_artifact(root, ref)


def test_cmu_artifact_keeps_native_schema_and_short_support(tmp_path):
    model = SurvivalModel((-2.0, 0.0, 0.1), (3.0,), (1.0,), True, 3, True, 1)
    artifact = RecoveryArtifact(model, CMU)
    root = tmp_path / "cmu"
    loaded = load_artifact(root, save_artifact(root, artifact, "synthetic-cmu"))
    assert loaded.cohort == CMU
    assert loaded.feature_order == ("jackson_adjusted",)
    assert loaded.research_payload("synthetic-episode", (4.0,)).supported_follow_up_days == 3
    with pytest.raises(ValueError, match="native"):
        loaded.research_payload("synthetic-episode", (1.0, 2.0, 3.0))
