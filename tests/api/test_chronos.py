"""Chronos-2 serving through a fake GX10: verified quantiles, honest failures, no identities."""

import hashlib
import json

import pytest

from hachi.api.artifacts import ArtifactRefused, ServingSpec, load_served_artifact, stage_artifact
from hachi.api.gpu import LOCAL_INFERENCE, GpuTimeout, GpuUnavailable, Gx10Target
from hachi.contracts.api import ReportJob
from hachi.contracts.manifests import ModelRef, RunManifest
from hachi.data.pmdata import dataset_snapshot_ref
from hachi.evaluation.serialization import document_bytes
from hachi.models.chronos import ChronosConfig, ChronosModelPin
from hachi.models.chronos.artifacts import ChronosArtifact, save_artifact
from hachi.models.chronos.inference import PREDICTION_FORMAT, REQUEST_FORMAT, canonical_bytes

from .conftest import FIT_AS_OF, GIT_SHA, HR_POLICY, make_packet, wait

PIN = ChronosModelPin(
    model_id="amazon/chronos-2",
    revision="29ec3766d36d6f73f0696f85560a422f50e8498c",
    weights_sha256="d" * 64,
    license="Apache-2.0",
    runtime_lock_sha256="8e30ab7405c3087d" + "0" * 48,
)
LEVELS = [0.1, 0.5, 0.9]
FORECAST = {
    "schema_version": "0.1",
    "subject_id": "p01",
    "as_of": "2020-03-29T12:00:00Z",
    "task": "physiology_forecast",
    "resolution": "hour",
    "horizon_hours": 24,
    "metrics": ["heart_rate"],
}


class FakeGx10:
    """Behaves like gpu-run + inference.py: one verified job per request file."""

    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.files: dict[str, bytes] = {}
        self.jobs: list[str] = []
        self.requests: list[dict] = []

    def home(self) -> str:
        if self.mode == "unreachable":
            raise GpuUnavailable("the GX10 could not be reached")
        return "/home/fake"

    def write(self, path: str, data: bytes) -> None:
        self.files[path] = data

    def remove(self, path: str) -> None:
        self.files.pop(path, None)

    def read(self, path: str) -> bytes:
        return self.files[path]

    def run(self, command: list[str], cwd: str, timeout: float) -> int:
        assert command[0] == "scripts/gx10/gpu-run" and cwd == "/remote/api-serving"
        run_id = command[command.index("--run-id") + 1]
        self.jobs.append(run_id)
        if self.mode == "busy":
            return 75
        if self.mode == "timeout":
            raise GpuTimeout("the GPU job did not finish in time")
        request_bytes = self.files[command[command.index("--requests") + 1]]
        row = json.loads(request_bytes)
        self.requests.append(row)
        observed = [v for v in row["context"] if v is not None]
        level = sum(observed) / len(observed)
        quantiles = [
            [level - 4.0 - step * 0.1, level + step * 0.1, level + 4.0 + step * 0.1]
            for step in range(row["prediction_length"])
        ]
        predictions = canonical_bytes({"request_id": row["request_id"], "quantiles": quantiles})
        evidence = {
            "format": PREDICTION_FORMAT,
            "request_format": REQUEST_FORMAT,
            "model": {"model_id": PIN.model_id, "revision": PIN.revision},
            "weights_sha256": "e" * 64 if self.mode == "wrong_weights" else PIN.weights_sha256,
            "environment": {
                "script_sha256": "f" * 64
                if self.mode == "other_script"
                else hashlib.sha256(LOCAL_INFERENCE.read_bytes()).hexdigest()
            },
            "requests_sha256": hashlib.sha256(request_bytes).hexdigest(),
            "predictions_sha256": hashlib.sha256(predictions).hexdigest(),
            "quantile_levels": LEVELS,
        }
        if self.mode == "tampered":
            predictions = predictions.replace(b"[", b"[ ", 1)
        directory = f"/home/fake/hachi/runs/tester/{run_id}"
        self.files[f"{directory}/inference.json"] = json.dumps(evidence).encode()
        self.files[f"{directory}/predictions.jsonl"] = predictions
        return 0


@pytest.fixture
def chronos_pin(tmp_path, data_root, snapshot_id):
    """A staged zero-shot Chronos artifact with its packet, like SwiftGorge's receipt."""

    def build(**serving_changes):
        config = ChronosConfig(model=PIN, metric="heart_rate", aggregation="mean", context_hours=48)
        artifact = ChronosArtifact(
            model_id="chronos-2-zero-shot",
            chronos=config,
            protocol_sha256="a" * 64,
            harness_lookback_hours=48,
        )
        base = tmp_path / f"chronos-{len(list(tmp_path.glob('chronos-*')))}"
        base.mkdir()
        ref = save_artifact(base / "model", artifact, artifact_id="chronos-2-zero-shot-test")
        packet = make_packet(base / "baseline", data_root / "derived" / snapshot_id)
        # Reuse the synthetic split/config; the run manifest names the Chronos artifact.
        split = (packet.packet_dir / "split.json").read_bytes()
        evaluation = (packet.packet_dir / "config.json").read_bytes()
        run = RunManifest(
            schema_version="0.1",
            run_id="synthetic-chronos-run",
            created_at_utc=FIT_AS_OF,
            git_sha=GIT_SHA,
            git_dirty=False,
            config_sha256=hashlib.sha256(evaluation).hexdigest(),
            dataset_snapshot=dataset_snapshot_ref(data_root / "derived" / snapshot_id),
            split_manifest_sha256=hashlib.sha256(split).hexdigest(),
            task="physiology_forecast",
            feature_order=["heart_rate"],
            model=ModelRef(
                model_id="chronos-2-zero-shot",
                checkpoint_source="amazon/chronos-2",
                checkpoint_revision=PIN.revision,
                license="Apache-2.0",
            ),
            environment_sha256=PIN.runtime_lock_sha256,
            seed=7,
            artifact=ref,
            metrics_paths=["evaluation.json"],
        )
        packet_dir = base / "packet"
        packet_dir.mkdir()
        (packet_dir / "run.json").write_bytes(document_bytes(run))
        (packet_dir / "split.json").write_bytes(split)
        (packet_dir / "config.json").write_bytes(evaluation)
        serving = ServingSpec(
            format_version="hachi-serving-1",
            task="physiology_forecast",
            resolution="hour",
            entry_point="hachi.models.chronos.artifacts.load_artifact",
            input="hourly_features",
            feature_policy=HR_POLICY,
            interval_nominal_coverage=0.8,
            requires_gpu=True,
            protocol_sha256="a" * 64,
        ).model_copy(update=serving_changes)
        root = tmp_path / "chronos-artifacts"
        root.mkdir(exist_ok=True)
        return root, stage_artifact(root, base / "model", packet_dir, serving)

    return build


@pytest.fixture
def chronos_client(open_client, make_settings, chronos_pin, monkeypatch):
    def factory(mode: str = "ok", *, configured: bool = True):
        fake = FakeGx10(mode)
        target = Gx10Target(transport=fake, owner="tester", checkout="/remote/api-serving")
        monkeypatch.setattr(
            "hachi.api.catalog.gx10_target", lambda _s: target if configured else None
        )
        root, pin = chronos_pin()
        client = open_client(make_settings(artifact_root=root, served_artifacts=(pin,)))
        return client, fake, pin

    return factory


def report(client, body=FORECAST) -> ReportJob:
    response = client.post("/v1/reports", json=body)
    assert response.status_code in (200, 202), response.text
    wait(client)
    return ReportJob.model_validate_json(
        client.get(f"/v1/reports/{response.json()['report_id']}").content
    )


def test_chronos_forecast_carries_real_uncalibrated_intervals(chronos_client):
    from hachi.api.handoff import Tally, api_points, direct_inference, expected_points

    client, fake, pin = chronos_client()
    job = report(client)
    result = job.result.root
    assert result.status == "ok", result
    series = result.forecast.series[0]
    assert (series.interval_calibration, series.nominal_coverage) == ("uncalibrated", 0.8)
    assert all(p.lower < p.median < p.upper for p in series.points)
    assert "UNCALIBRATED_INTERVALS" in {w.code for w in result.warnings}
    assert result.provenance.artifact == pin
    # One GPU job; the GX10 sees the context and horizon only, never who or when.
    assert len(fake.jobs) == 1 and fake.jobs[0].startswith("api-chronos-")
    assert set(fake.requests[0]) == {"request_id", "context", "prediction_length"}
    assert "p01" not in json.dumps(fake.requests) + fake.jobs[0]
    assert not any(path.endswith(".jsonl") and "api-requests" in path for path in fake.files)

    service = client.app.state.service
    served = service.catalog.artifacts[0]
    subject = service.catalog.subject("p01", service.metadata, service.workspace)
    tally = Tally()
    tally.add(
        api_points(job),
        expected_points(result.as_of, direct_inference(served, subject, result.as_of, 24)),
    )
    assert tally.agrees and tally.with_intervals == tally.compared == 24


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("busy", "GPU_UNAVAILABLE"),
        ("unreachable", "GPU_UNAVAILABLE"),
        ("timeout", "INFERENCE_TIMEOUT"),
        ("tampered", "INFERENCE_FAILED"),
        ("wrong_weights", "INFERENCE_FAILED"),
        ("other_script", "INFERENCE_FAILED"),
    ],
)
def test_gpu_failures_are_errors_never_guesses(chronos_client, mode, code):
    client, _, _ = chronos_client(mode)
    result = report(client).result.root
    assert result.status == "error" and result.error_code == code
    retry = client.post("/v1/reports", json=FORECAST)
    if code != "INFERENCE_FAILED":  # transient: an identical request runs again
        assert retry.status_code == 202


def test_without_a_gx10_the_gpu_model_is_unavailable(chronos_client):
    client, fake, _ = chronos_client(configured=False)
    result = report(client).result.root
    assert result.status == "error" and result.error_code == "GPU_UNAVAILABLE"
    assert fake.jobs == []


@pytest.mark.parametrize(
    "changes",
    [
        {"interval_nominal_coverage": 0.9},
        {"requires_gpu": False},
        {"protocol_sha256": "b" * 64},
    ],
)
def test_incompatible_chronos_serving_is_refused(chronos_pin, changes):
    with pytest.raises(ArtifactRefused) as refused:
        chronos_pin(**changes)
    assert refused.value.code == "ARTIFACT_INCOMPATIBLE"


def test_staged_chronos_artifact_loads_with_its_pin(chronos_pin):
    root, pin = chronos_pin()
    served = load_served_artifact(root, pin)
    assert served.model.model_id == "chronos-2-zero-shot" and served.metric == "heart_rate"
    assert served.serving.requires_gpu and served.model.target is None  # no GX10 given here
    assert served.model.fit_as_of is None  # zero-shot: no cohort fit cutoff


def test_ssh_jobs_carry_their_own_gx10_deadline(monkeypatch):
    import subprocess

    from hachi.api import gpu

    seen = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 124, b"", b"")

    monkeypatch.setattr(gpu.subprocess, "run", fake_run)
    code = gpu.SshTransport("asus@gx10").run(["scripts/gx10/gpu-run", "--x"], "/remote", 120)
    remote = seen[0][-1]
    assert code == 124 and remote.startswith("cd /remote && timeout --kill-after=10 105 ")
    assert seen[0][:3] == ["ssh", "-o", "BatchMode=yes"]

    class Remote:
        def home(self):
            return "/home/fake"

        def write(self, path, data):
            pass

        def remove(self, path):
            pass

        def run(self, command, cwd, timeout):
            return 124  # the GX10's own deadline fired, e.g. while queued on the GPU lock

    target = gpu.Gx10Target(transport=Remote(), owner="tester", checkout="/remote")
    with pytest.raises(GpuTimeout):
        gpu.chronos_quantiles(
            target, PIN, {"request_id": "r", "context": [1.0], "prediction_length": 1}
        )
