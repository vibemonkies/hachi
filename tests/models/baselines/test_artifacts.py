import hashlib
import json

import pytest

from hachi.models.baselines import load_artifact, save_artifact

from .test_forecast import artifact, request, row


def test_private_snapshot_readback_checks_reference_content_and_source(tmp_path):
    fitted = artifact("train_population_mean", [row("train-a", -1, 60.0)])
    path = tmp_path / "model"
    reference = save_artifact(path, fitted, artifact_id="generated-mean")
    assert load_artifact(path, reference).predict(request()) == fitted.predict(request())
    assert path.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in path.iterdir())
    with pytest.raises(FileExistsError):
        save_artifact(path, fitted, artifact_id="generated-mean")
    (path / "model.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="checksum"):
        load_artifact(path, reference)


def test_incompatible_source_is_refused_even_with_a_new_valid_content_reference(tmp_path):
    from hachi.contracts.base import ArtifactRef
    from hachi.evaluation.serialization import document_bytes, document_sha256
    from hachi.models.baselines.artifacts import Receipt

    path = tmp_path / "model"
    save_artifact(path, artifact("last_valid"), artifact_id="generated-last")
    sources = json.loads((path / "source-sha256.json").read_text())
    sources["forecast.py"] = "a" * 64
    data = document_bytes(sources)
    (path / "source-sha256.json").write_bytes(data)
    receipt = Receipt.model_validate_json((path / "artifact.json").read_bytes())
    receipt = Receipt(
        artifact_id=receipt.artifact_id,
        files={**receipt.files, "source-sha256.json": hashlib.sha256(data).hexdigest()},
    )
    (path / "artifact.json").write_bytes(document_bytes(receipt))
    reference = ArtifactRef(
        artifact_id=receipt.artifact_id, artifact_sha256=document_sha256(receipt)
    )
    with pytest.raises(ValueError, match="identified baseline implementation"):
        load_artifact(path, reference)
