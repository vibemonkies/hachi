"""Generated-only GPU transport/identity privacy; never connect to or queue a GPU."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from hachi.api.gpu import (
    LOCAL_INFERENCE,
    GpuOutputRejected,
    GpuTimeout,
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


class Remote:
    """Generated remote inventory with failures at the same transport boundaries as SSH.

    remove supports a tree for the probe; the source owner chooses the production
    deletion API. Adapt that method only when the owner's design is agreed.
    """

    def __init__(self, mode="ok", cleanup_failure=None):
        self.mode = mode
        self.cleanup_failure = cleanup_failure
        self.files = {"/generated/hachi/runs/privacy-test/unrelated/keep": b"generated sibling"}
        self.calls = []
        self.request_path = None
        self.run_dir = None

    def home(self):
        self.calls.append("home")
        return "/generated"

    def write(self, path, data):
        self.calls.append("write")
        self.request_path = path
        self.files[path] = data
        if self.mode == "partial_write":
            raise GpuUnavailable("generated partial write failure")

    def remove(self, path):
        target = "request" if "/api-requests/" in path else "output"
        self.calls.append("remove_" + target)
        if self.cleanup_failure in (target, "both"):
            raise GpuUnavailable(SENTINEL)
        self.files = {
            key: value
            for key, value in self.files.items()
            if key != path and not key.startswith(path + "/")
        }

    def read(self, path):
        self.calls.append("read")
        if self.mode == "read_failure":
            raise GpuUnavailable("generated read failure")
        return self.files[path]

    def run(self, command, cwd, timeout):
        self.calls.append("run")
        if self.mode == "busy":
            return 75
        request = self.files[command[command.index("--requests") + 1]]
        row = json.loads(request)
        run_id = command[command.index("--run-id") + 1]
        self.run_dir = f"/generated/hachi/runs/privacy-test/{run_id}"
        predictions = canonical_bytes(
            {
                "request_id": SENTINEL if self.mode == "integrity_failure" else row["request_id"],
                "quantiles": [[65, 70, 75]] * row["prediction_length"],
            }
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
        self.files[self.run_dir + "/inference.json"] = json.dumps(evidence).encode()
        self.files[self.run_dir + "/predictions.jsonl"] = predictions
        self.files[self.run_dir + "/output.log"] = SENTINEL.encode()
        self.files[self.run_dir + "/job.json"] = b"generated metadata"
        self.files[self.run_dir + "/nested/partial-context.bin"] = request
        if self.mode == "timeout":
            raise GpuTimeout("generated timeout")
        if self.mode == "unexpected":
            raise RuntimeError(SENTINEL)
        if self.mode == "nonzero":
            return 1
        return 0


class FileRemote(Remote):
    """The same generated transport with actual files under one owned disposable root."""

    def __init__(self, root, mode="ok", cleanup_failure=None):
        super().__init__(mode, cleanup_failure)
        self.root = root
        self.root.mkdir(mode=0o700)
        self.publish()

    def local(self, path):
        destination = self.root / Path(path).relative_to("/generated")
        assert destination.resolve().is_relative_to(self.root.resolve())
        return destination

    def publish(self):
        for path, body in self.files.items():
            destination = self.local(path)
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination.write_bytes(body)

    def write(self, path, data):
        try:
            return super().write(path, data)
        finally:
            self.publish()

    def run(self, command, cwd, timeout):
        try:
            return super().run(command, cwd, timeout)
        finally:
            self.publish()

    def read(self, path):
        super().read(path)
        return self.local(path).read_bytes()

    def remove(self, path):
        super().remove(path)
        destination = self.local(path)
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink(missing_ok=True)


@pytest.fixture(params=("memory", "filesystem"))
def remote_factory(tmp_path, request):
    def create(mode, cleanup_failure=None):
        if request.param == "filesystem":
            return FileRemote(tmp_path / "private-remote", mode, cleanup_failure)
        return Remote(mode, cleanup_failure)

    yield create
    # Only this test's own generated root; never source caches or another worker's state.
    shutil.rmtree(tmp_path)


def require_clean_inventory(remote):
    remaining = len(remote.files)
    assert remaining == 1, "owned remote artifacts remain"
    assert "/generated/hachi/runs/privacy-test/unrelated/keep" in remote.files
    if isinstance(remote, FileRemote):
        files_remaining = sum(path.is_file() for path in remote.root.rglob("*"))
        assert files_remaining == 1, "owned filesystem artifacts remain"


def invoke(remote):
    from hachi.api.gpu import Gx10Target, chronos_quantiles

    return chronos_quantiles(
        Gx10Target(transport=remote, owner="privacy-test", checkout="/generated"),
        PIN,
        {"request_id": "generated", "context": [70], "prediction_length": 1},
    )


@pytest.mark.parametrize(
    "mode",
    [
        "ok",
        "busy",
        "nonzero",
        "timeout",
        "partial_write",
        "read_failure",
        "integrity_failure",
        "unexpected",
    ],
)
def test_complete_owned_remote_inventory_erased_on_every_exit(mode, remote_factory):
    remote = remote_factory(mode)
    if mode == "ok":
        assert invoke(remote).rows == ((65, 70, 75),)
    else:
        with pytest.raises(
            {
                "timeout": GpuTimeout,
                "integrity_failure": GpuOutputRejected,
                "unexpected": RuntimeError,
            }.get(mode, GpuUnavailable)
        ):
            invoke(remote)
    # Count and sibling identity only: never print request/context or output contents.
    require_clean_inventory(remote)


@pytest.mark.parametrize("cleanup_failure", ["request", "output", "both"])
@pytest.mark.parametrize("mode", ["ok", "integrity_failure"])
def test_cleanup_failure_is_safe_and_attempts_both_inventories(
    mode, cleanup_failure, remote_factory
):
    remote = remote_factory(mode, cleanup_failure)
    with pytest.raises((GpuUnavailable, GpuOutputRejected)) as error:
        invoke(remote)
    assert SENTINEL not in str(error.value)
    assert "remove_request" in remote.calls and "remove_output" in remote.calls
    assert "/generated/hachi/runs/privacy-test/unrelated/keep" in remote.files
