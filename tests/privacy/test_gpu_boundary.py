"""Generated-only GPU transport/identity privacy; never connect to or queue a GPU."""

import hashlib
import json
import subprocess

import pytest

pytest.importorskip("fastapi")
from hachi.api.gpu import (
    LOCAL_INFERENCE,
    GpuOutputRejected,
    GpuUnavailable,
    SshTransport,
    _verified,
)
from hachi.models.chronos import ChronosModelPin
from hachi.models.chronos.inference import PREDICTION_FORMAT, REQUEST_FORMAT, canonical_bytes

SENTINEL = "SYNTHETIC-REMOTE-PRIVATE-SENTINEL"
PIN = ChronosModelPin(
    model_id="amazon/chronos-2",
    revision="a" * 40,
    weights_sha256="b" * 64,
    license="Apache-2.0",
    runtime_lock_sha256="c" * 64,
)


def test_ssh_stderr_is_not_exposed_and_password_prompts_are_disabled(monkeypatch):
    calls = []

    def failed(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 255, b"", SENTINEL.encode())

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(GpuUnavailable) as error:
        SshTransport("generated@invalid").home()
    assert SENTINEL not in str(error.value)
    argv, kwargs = calls[0]
    assert "BatchMode=yes" in argv and kwargs["capture_output"]


@pytest.mark.parametrize(
    "mutation", ["request_id", "duplicate", "request_hash", "model_revision", "weights"]
)
def test_gpu_identity_mismatch_refuses_output_without_echo(mutation):
    row = {"request_id": "generated-request", "context": [70.0], "prediction_length": 1}
    request = canonical_bytes(row)
    prediction = {"request_id": row["request_id"], "quantiles": [[65.0, 70.0, 75.0]]}
    if mutation == "request_id":
        prediction["request_id"] = SENTINEL
    predictions = canonical_bytes(prediction)
    if mutation == "duplicate":
        predictions += predictions
    evidence = {
        "format": PREDICTION_FORMAT,
        "request_format": REQUEST_FORMAT,
        "model": {"model_id": PIN.model_id, "revision": PIN.revision},
        "weights_sha256": PIN.weights_sha256,
        "environment": {"script_sha256": hashlib.sha256(LOCAL_INFERENCE.read_bytes()).hexdigest()},
        "requests_sha256": hashlib.sha256(request).hexdigest(),
        "predictions_sha256": hashlib.sha256(predictions).hexdigest(),
        "quantile_levels": [0.1, 0.5, 0.9],
    }
    if mutation == "request_hash":
        evidence["requests_sha256"] = SENTINEL
    if mutation == "model_revision":
        evidence["model"]["revision"] = SENTINEL
    if mutation == "weights":
        evidence["weights_sha256"] = SENTINEL
    with pytest.raises(GpuOutputRejected) as error:
        _verified(json.dumps(evidence).encode(), predictions, request, row, PIN, "generated-run")
    assert SENTINEL not in str(error.value)


@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_remote_artifacts_are_outside_subject_erasure_inventory(cleanup_failure):
    """Bind the documented personal-GPU gate to observed transport retention behavior."""
    from hachi.api.gpu import Gx10Target, chronos_quantiles

    class Remote:
        def __init__(self):
            self.files = {}

        def home(self):
            return "/generated"

        def write(self, path, data):
            self.files[path] = data

        def remove(self, path):
            if cleanup_failure:
                raise GpuUnavailable(SENTINEL)
            self.files.pop(path, None)

        def read(self, path):
            return self.files[path]

        def run(self, command, cwd, timeout):
            request = self.files[command[command.index("--requests") + 1]]
            row = json.loads(request)
            run_id = command[command.index("--run-id") + 1]
            directory = f"/generated/hachi/runs/privacy-test/{run_id}"
            predictions = canonical_bytes(
                {"request_id": row["request_id"], "quantiles": [[65, 70, 75]]}
            )
            evidence = {
                "format": PREDICTION_FORMAT,
                "request_format": REQUEST_FORMAT,
                "model": {"model_id": PIN.model_id, "revision": PIN.revision},
                "weights_sha256": PIN.weights_sha256,
                "environment": {
                    "script_sha256": hashlib.sha256(LOCAL_INFERENCE.read_bytes()).hexdigest()
                },
                "requests_sha256": hashlib.sha256(request).hexdigest(),
                "predictions_sha256": hashlib.sha256(predictions).hexdigest(),
                "quantile_levels": [0.1, 0.5, 0.9],
            }
            self.files[directory + "/inference.json"] = json.dumps(evidence).encode()
            self.files[directory + "/predictions.jsonl"] = predictions
            return 0

    remote = Remote()
    target = Gx10Target(transport=remote, owner="privacy-test", checkout="/generated")
    result = chronos_quantiles(
        target, PIN, {"request_id": "generated", "context": [70], "prediction_length": 1}
    )
    assert result.rows == ((65, 70, 75),)
    assert any("api-requests" in path for path in remote.files) == cleanup_failure
    outputs = {path.rsplit("/", 1)[-1] for path in remote.files if "/runs/" in path}
    assert outputs == {"predictions.jsonl", "inference.json"}
