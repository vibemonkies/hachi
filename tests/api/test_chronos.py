"""Chronos-2 serving through a fake GX10: verified quantiles, honest failures, no identities."""

import hashlib
import json
from datetime import timedelta

import pytest

from hachi.api.artifacts import (
    ArtifactRefused,
    ServingSpec,
    SourceAdmission,
    load_served_artifact,
    stage_artifact,
)
from hachi.api.gpu import LOCAL_INFERENCE, GpuTimeout, GpuUnavailable, Gx10Target
from hachi.contracts.api import ReportJob
from hachi.contracts.manifests import ModelRef, RunManifest
from hachi.data.apple_health.hourly import AVAILABILITY_RULE
from hachi.data.pmdata import dataset_snapshot_ref
from hachi.evaluation.context import ContextPolicy
from hachi.evaluation.serialization import document_bytes
from hachi.models.chronos import ChronosConfig, ChronosModelPin
from hachi.models.chronos.artifacts import ChronosArtifact, save_artifact
from hachi.models.chronos.inference import PREDICTION_FORMAT, REQUEST_FORMAT, canonical_bytes

from .conftest import FIT_AS_OF, GIT_SHA, HR_POLICY, make_packet, upload, wait

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
        self.terminated: list[str] = []

    def home(self) -> str:
        if self.mode == "unreachable":
            raise GpuUnavailable("the GX10 could not be reached")
        return "/home/fake"

    def write(self, path: str, data: bytes) -> None:
        self.files[path] = data

    def remove(self, path: str) -> None:
        self.files.pop(path, None)

    def remove_tree(self, path: str) -> None:
        if self.mode == "stuck_cleanup":
            raise GpuUnavailable("remote step failed (exit 1)")
        for name in [f for f in self.files if f.startswith(path + "/")]:
            del self.files[name]

    def terminate(self, marker: str) -> None:
        self.terminated.append(marker)
        if self.mode == "unkillable":
            raise GpuUnavailable("remote step failed (exit 1)")

    def read(self, path: str) -> bytes:
        return self.files[path]

    def run(self, command: list[str], cwd: str, timeout: float) -> int:
        assert command[0] == "scripts/gx10/gpu-run" and cwd == "/remote/api-serving"
        run_id = command[command.index("--run-id") + 1]
        self.jobs.append(run_id)
        if self.mode == "busy":
            return 75
        directory = f"/home/fake/hachi/runs/tester/{run_id}"
        self.files[f"{directory}/job.json"] = b'{"state": "running"}'  # gpu-run's own record
        self.files[f"{directory}/output.log"] = b"supervisor output"
        if self.mode in ("timeout", "unkillable"):
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
        self.files[f"{directory}/inference.json"] = json.dumps(evidence).encode()
        self.files[f"{directory}/predictions.jsonl"] = predictions
        return 0


@pytest.fixture
def chronos_pin(tmp_path, data_root, snapshot_id):
    """A staged zero-shot Chronos artifact with its packet, like SwiftGorge's receipt."""

    def build(*, context=None, context_hours=48, covariates=(), **serving_changes):
        config = ChronosConfig(
            model=PIN, metric="heart_rate", aggregation="mean", context_hours=context_hours
        )
        artifact = ChronosArtifact(
            model_id="chronos-2-zero-shot",
            chronos=config,
            protocol_sha256="a" * 64,
            harness_lookback_hours=48,
            context_policy=context,
            past_covariates=list(covariates),
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
        root = base / "artifacts"  # one root per staging: artifacts are immutable
        root.mkdir()
        return root, stage_artifact(root, base / "model", packet_dir, serving)

    return build


@pytest.fixture
def chronos_client(open_client, make_settings, chronos_pin, monkeypatch):
    def factory(mode: str = "ok", *, configured: bool = True, serving_changes=None, artifact=None):
        fake = FakeGx10(mode)
        target = Gx10Target(transport=fake, owner="tester", checkout="/remote/api-serving")
        monkeypatch.setattr(
            "hachi.api.catalog.gx10_target", lambda _s: target if configured else None
        )
        root, pin = chronos_pin(**(serving_changes or {}), **(artifact or {}))
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

        def remove_tree(self, path):
            pass

        def terminate(self, marker):
            raise AssertionError("the remote deadline already ended this job")

        def run(self, command, cwd, timeout):
            return 124  # the GX10's own deadline fired, e.g. while queued on the GPU lock

    target = gpu.Gx10Target(transport=Remote(), owner="tester", checkout="/remote")
    with pytest.raises(GpuTimeout):
        gpu.chronos_quantiles(
            target, PIN, {"request_id": "r", "context": [1.0], "prediction_length": 1}
        )


def test_nothing_from_a_request_outlives_it_on_the_gx10(chronos_client):
    client, fake, _ = chronos_client()
    assert report(client).result.root.status == "ok"
    assert fake.jobs and fake.files == {}  # request and the whole run directory removed
    assert fake.terminated == []  # the job ended normally, nothing to stop


def test_a_job_with_an_unknown_end_is_stopped_before_its_files_are_removed(chronos_client):
    client, fake, _ = chronos_client("timeout")
    result = report(client).result.root
    assert (result.status, result.error_code) == ("error", "INFERENCE_TIMEOUT")
    assert fake.terminated == fake.jobs and fake.files == {}
    stuck_client, stuck, _ = chronos_client("unkillable")
    assert stuck.terminated == []
    stuck_result = report(stuck_client, FORECAST | {"as_of": "2020-03-29T13:00:00Z"}).result.root
    assert (stuck_result.status, stuck_result.error_code) == ("error", "INFERENCE_FAILED")
    assert "could not be removed" in stuck_result.message
    assert stuck.terminated == stuck.jobs  # termination was attempted, and its failure surfaced


def test_a_failed_gx10_cleanup_is_surfaced_and_the_forecast_withheld(chronos_client):
    failing, stuck, _ = chronos_client("stuck_cleanup")
    result = report(failing).result.root
    assert result.status == "error" and result.error_code == "INFERENCE_FAILED"
    assert "could not be removed" in result.message  # surfaced, never suppressed
    assert any(path.endswith("predictions.jsonl") for path in stuck.files)


def test_personal_imports_never_reach_the_shared_gpu(chronos_client, chronos_pin):
    from hachi.api.artifacts import SourceAdmission

    from .test_apple_serving import APPLE_POLICY, apple_hr_export

    admission = SourceAdmission(
        source="apple_health", feature_policy=APPLE_POLICY, rationale="transfer test"
    )
    client, fake, _ = chronos_client(serving_changes={"accepted_sources": [admission]})
    upload(client, apple_hr_export(72), subject="person-001", data_mode="real")
    wait(client)
    personal = report(
        client, FORECAST | {"subject_id": "person-001", "as_of": "2026-09-03T12:00:00Z"}
    )
    result = personal.result.root
    assert (result.status, result.reason_code) == ("unavailable", "NO_ARTIFACT_FOR_TASK")
    assert "retention design" in result.requirements[0]
    assert fake.jobs == []  # nothing was sent to the GX10
    upload(client, apple_hr_export(72), subject="synthetic-apple-gpu")  # generated data
    wait(client)
    generated = report(
        client, FORECAST | {"subject_id": "synthetic-apple-gpu", "as_of": "2026-09-03T12:00:00Z"}
    )
    assert generated.result.root.status == "ok" and len(fake.jobs) == 1


STEPS = HR_POLICY.model_copy(update={"metric": "steps", "aggregation": "sum"})
CONTEXT = ContextPolicy(hours=96, channels=[HR_POLICY, STEPS])
APPLE = SourceAdmission(
    source="apple_health",
    rationale="generated probe",
    feature_policy=HR_POLICY.model_copy(update={"availability_rule": AVAILABILITY_RULE}),
)


def forecast_windows(cutoff):
    from hachi.contracts.manifests import TimeWindow

    return tuple(
        TimeWindow(start_utc=cutoff + timedelta(hours=i), end_utc=cutoff + timedelta(hours=i + 1))
        for i in range(24)
    )


def test_a_longer_context_is_built_exactly_as_12_evaluated_it(chronos_client):
    """#12's ctx720 shape: the 48 h harness history plus a longer context from the index."""
    from hachi.api.handoff import Tally, api_points, direct_inference, expected_points
    from hachi.data.pmdata import iter_aggregates
    from hachi.evaluation import ForecastInput
    from hachi.evaluation.context import context_index
    from hachi.models.chronos.adapter import extended_builder

    client, fake, _ = chronos_client(artifact={"context": CONTEXT, "context_hours": 96})
    # Late enough that the synthetic data reaches past the 48 h harness window.
    job = report(client, FORECAST | {"as_of": "2020-03-30T12:00:00Z"})
    result = job.result.root
    assert result.status == "ok", result
    sent = fake.requests[0]
    assert len(sent["context"]) == 96
    assert set(sent) == {"request_id", "context", "prediction_length"}

    # The evaluator's construction: one index over the whole snapshot, then extended_builder.
    service = client.app.state.service
    served = service.catalog.artifacts[0]
    subject = service.catalog.subject("p01", service.metadata, service.workspace)
    cutoff = result.as_of
    everyone = context_index(iter_aggregates(subject.path, "hour"), CONTEXT)
    history = subject.hourly_features(HR_POLICY, cutoff, cutoff - timedelta(hours=48))
    model_input = ForecastInput("p01", cutoff, forecast_windows(cutoff), tuple(history))
    expected = extended_builder(
        served.model.config, everyone, context_hours=96, harness_lookback_hours=48
    )(model_input)
    assert (sent["context"], sent["request_id"]) == (list(expected.context), expected.request_id)
    assert sum(v is not None for v in sent["context"][:48]) > 0  # hours beyond the harness
    tally = Tally()
    tally.add(
        api_points(job),
        expected_points(result.as_of, direct_inference(served, subject, result.as_of, 24)),
    )
    assert tally.agrees and tally.compared == 24


@pytest.mark.parametrize(
    ("changes", "refusal"),
    [
        ({"context": CONTEXT, "context_hours": 96, "covariates": ["steps"]},
         "zero-shot univariate"),
        ({"context": CONTEXT, "context_hours": 120}, "declared window"),
        ({"context": ContextPolicy(hours=96, channels=[
            HR_POLICY.model_copy(update={"min_observed_count": 2}), STEPS]),
          "context_hours": 96}, "target channel"),
        ({"context": CONTEXT, "context_hours": 96, "accepted_sources": [APPLE]},
         "evaluated dataset only"),
    ],
)  # fmt: skip
def test_longer_contexts_are_served_only_as_evaluated(chronos_pin, changes, refusal):
    with pytest.raises(ArtifactRefused, match=refusal):
        chronos_pin(**changes)
