"""Artifacts load only after checksum, schema and feature-compatibility checks."""

import json

import pytest

from hachi.api.artifacts import ArtifactRefused, ServingSpec, load_served_artifact, stage_artifact
from hachi.contracts.base import ArtifactRef
from hachi.evaluation.features import HourlyFeaturePolicy
from hachi.models.baselines import BaselineConfig

from .conftest import HR_POLICY, make_packet


@pytest.fixture
def staged(tmp_path, data_root, snapshot_id):
    def factory(**options) -> tuple:
        base = tmp_path / f"packet-{len(list(tmp_path.iterdir()))}"
        base.mkdir()
        packet = make_packet(base, data_root / "derived" / snapshot_id, **options)
        root = tmp_path / "artifacts"
        root.mkdir(exist_ok=True)
        return root, packet

    return factory


def writable_copy(root, pin: ArtifactRef):
    directory = root / pin.artifact_id
    for path in [directory, directory / "model", *directory.rglob("*")]:
        path.chmod(0o700 if path.is_dir() else 0o600)
    return directory


def test_staged_artifact_loads_and_is_read_only(staged):
    root, packet = staged()
    pin = stage_artifact(root, packet.model_dir, packet.packet_dir, packet.serving, packet.protocol)
    served = load_served_artifact(root, pin)
    assert served.metric == "heart_rate" and served.model.model_id == "hourly-last-valid-v1"
    assert all(not p.stat().st_mode & 0o222 for p in (root / pin.artifact_id).rglob("*"))
    with pytest.raises(FileExistsError):
        stage_artifact(root, packet.model_dir, packet.packet_dir, packet.serving, packet.protocol)


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        (lambda d: (d / "model" / "model.json").write_bytes(b"{}"), "ARTIFACT_INTEGRITY_FAILED"),
        (lambda d: (d / "serving.json").unlink(), "ARTIFACT_INTEGRITY_FAILED"),
        (lambda d: (d / "notes.txt").write_text("x"), "ARTIFACT_INTEGRITY_FAILED"),
        (lambda d: (d / "split.json").write_text("{}"), "ARTIFACT_INTEGRITY_FAILED"),
        (
            lambda d: (d / "serving.json").write_text(
                json.dumps(json.loads((d / "serving.json").read_text()) | {"input": "raw"})
            ),
            "ARTIFACT_INCOMPATIBLE",
        ),
    ],
)
def test_altered_or_incomplete_artifacts_are_refused(staged, damage, code):
    root, packet = staged()
    pin = stage_artifact(root, packet.model_dir, packet.packet_dir, packet.serving, packet.protocol)
    damage(writable_copy(root, pin))
    with pytest.raises(ArtifactRefused) as refused:
        load_served_artifact(root, pin)
    assert refused.value.code == code


def test_a_pin_must_match_the_artifact(staged):
    root, packet = staged()
    pin = stage_artifact(root, packet.model_dir, packet.packet_dir, packet.serving, packet.protocol)
    wrong = ArtifactRef(artifact_id=pin.artifact_id, artifact_sha256="0" * 64)
    with pytest.raises(ArtifactRefused, match="pin"):
        load_served_artifact(root, wrong)
    for bad_id in ("../etc", "a/b", ".hidden"):
        with pytest.raises(ValueError):
            load_served_artifact(root, ArtifactRef.model_construct(artifact_id=bad_id))


def test_symlinked_artifacts_are_refused(staged, tmp_path):
    root, packet = staged()
    pin = stage_artifact(root, packet.model_dir, packet.packet_dir, packet.serving, packet.protocol)
    approved = tmp_path / "approved"
    approved.mkdir()
    (approved / pin.artifact_id).symlink_to(root / pin.artifact_id)
    with pytest.raises(ValueError, match="symlink"):
        load_served_artifact(approved, pin)


@pytest.mark.parametrize(
    "options",
    [
        {"feature_order": ["steps"]},
        {
            "serving": ServingSpec(
                format_version="hachi-serving-1",
                task="physiology_forecast",
                resolution="hour",
                entry_point="hachi.models.baselines.load_artifact",
                input="hourly_features",
                feature_policy=HourlyFeaturePolicy(
                    **(HR_POLICY.model_dump() | {"aggregation": "max"})
                ),
            )
        },
        {"config": BaselineConfig(method="last_valid", metric="heart_rate", aggregation="max")},
    ],
)
def test_feature_mismatch_is_incompatible(staged, options):
    root, packet = staged(**options)
    with pytest.raises(ArtifactRefused) as refused:
        stage_artifact(root, packet.model_dir, packet.packet_dir, packet.serving, packet.protocol)
    assert refused.value.code == "ARTIFACT_INCOMPATIBLE"
    assert not any(root.iterdir())  # nothing half-staged is left behind


def test_changed_model_code_is_incompatible(staged, monkeypatch):
    root, packet = staged()
    pin = stage_artifact(root, packet.model_dir, packet.packet_dir, packet.serving, packet.protocol)
    import hachi.models.baselines.artifacts as baseline_artifacts

    real = baseline_artifacts.source_hashes
    monkeypatch.setattr(baseline_artifacts, "source_hashes", lambda: real() | {"x.py": "0" * 64})
    with pytest.raises(ArtifactRefused) as refused:
        load_served_artifact(root, pin)
    assert refused.value.code == "ARTIFACT_INCOMPATIBLE"


def test_refused_artifacts_degrade_health_and_are_never_used(open_client, make_settings, served):
    _root, pin = served
    wrong = ArtifactRef(artifact_id=pin.artifact_id, artifact_sha256="1" * 64)
    client = open_client(make_settings(served_artifacts=(wrong,)))
    health = client.get("/healthz").json()
    assert health["status"] == "degraded" and health["artifacts"] == []
    assert "p01" not in json.dumps(health)
    body = {
        "schema_version": "0.1",
        "subject_id": "p01",
        "as_of": "2020-03-29T12:00:00Z",
        "task": "physiology_forecast",
        "resolution": "hour",
    }
    job = client.post("/v1/reports", json=body).json()
    assert client.app.state.service.runner.wait_idle(30)
    result = client.get(f"/v1/reports/{job['report_id']}").json()["result"]
    assert result["status"] == "unavailable" and result["reason_code"] == "NO_ARTIFACT_FOR_TASK"


def test_gpu_artifacts_report_the_gpu_honestly(open_client, make_settings, tmp_path, staged):
    root, packet = staged(artifact_id="synthetic-gpu-model")
    serving = packet.serving.model_copy(update={"requires_gpu": True})
    pin = stage_artifact(root, packet.model_dir, packet.packet_dir, serving, packet.protocol)
    client = open_client(make_settings(artifact_root=root, served_artifacts=(pin,)))
    body = {
        "schema_version": "0.1",
        "subject_id": "p01",
        "as_of": "2020-03-29T12:00:00Z",
        "task": "physiology_forecast",
        "resolution": "hour",
    }
    job = client.post("/v1/reports", json=body).json()
    assert client.app.state.service.runner.wait_idle(30)
    result = client.get(f"/v1/reports/{job['report_id']}").json()["result"]
    assert result["status"] == "error" and result["error_code"] == "GPU_UNAVAILABLE"
    # A transient failure is retried by an identical request rather than replayed.
    again = client.post("/v1/reports", json=body)
    assert again.status_code == 202 and again.json()["report_id"] != job["report_id"]
