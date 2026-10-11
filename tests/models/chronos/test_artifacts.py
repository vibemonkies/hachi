import json

import pytest
from pydantic import ValidationError

from hachi.contracts.base import ArtifactRef
from hachi.models.chronos.artifacts import (
    ChronosArtifact,
    artifact_id_for,
    load_artifact,
    save_artifact,
)


def artifact(chronos, **update):
    fields = {
        "model_id": "chronos-2-zero-shot",
        "chronos": chronos,
        "protocol_sha256": "a" * 64,
        "harness_lookback_hours": chronos.context_hours,
    }
    return ChronosArtifact(**{**fields, **update})


def test_receipt_round_trip_and_tamper_refusal(tmp_path, chronos):
    saved = artifact(chronos)
    ref = save_artifact(tmp_path / "m", saved, artifact_id=artifact_id_for(saved))
    assert load_artifact(tmp_path / "m", ref) == saved
    assert saved.weights_sha256 == chronos.model.weights_sha256
    with pytest.raises(ValueError, match="expected immutable reference"):
        load_artifact(
            tmp_path / "m", ArtifactRef(artifact_id=ref.artifact_id, artifact_sha256="0" * 64)
        )
    model = tmp_path / "m" / "model.json"
    model.chmod(0o600)
    model.write_text(json.dumps({**json.loads(model.read_text()), "model_id": "other"}))
    with pytest.raises(ValueError, match="checksum"):
        load_artifact(tmp_path / "m", ref)
    with pytest.raises(FileExistsError):
        save_artifact(tmp_path / "m", saved, artifact_id=ref.artifact_id)


def test_variants_need_a_context_policy_and_fine_tunes_need_both_hashes(chronos):
    with pytest.raises(ValidationError, match="context policy"):
        artifact(chronos, harness_lookback_hours=4)
    with pytest.raises(ValidationError, match="both"):
        artifact(chronos, finetuned_weights_sha256="b" * 64)
    tuned = artifact(chronos, finetuned_weights_sha256="b" * 64, finetune_receipt_sha256="c" * 64)
    assert tuned.weights_sha256 == "b" * 64
