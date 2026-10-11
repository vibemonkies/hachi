"""GPU inference on the GX10 for served models, through `scripts/gx10/gpu-run` over SSH.

The API runs on a laptop; Chronos-2 runs only in the pinned GX10 runtime (#10). For each
forecast the client writes one causal context request (no subject id, cutoff or target),
runs #10's `src/hachi/models/chronos/inference.py` under the cooperative GPU queue, reads
back `inference.json` and `predictions.jsonl`, and verifies before anything is used:

- the run used the pinned weights (`weights_sha256`) and model revision,
- the GX10 ran the same inference script as this checkout (`script_sha256`),
- `requests_sha256` and `predictions_sha256` match the bytes sent and received,
- exactly one prediction answers this request id, with the requested horizon.

A busy GPU (gpu-run exit 75), an unreachable host or a failed job is `GpuUnavailable`; a
job past its deadline is `GpuTimeout`; output that fails verification is
`GpuOutputRejected`. Nothing is ever guessed in their place.

Nothing derived from the request outlives it on the GX10: the request file and the run's
`predictions.jsonl` and `inference.json` are removed after every job, successful or not.
If any removal fails the forecast is not used (`GpuCleanupFailed`); failures are never
suppressed. The supervisor's own `job.json` and `output.log` hold no request content.
"""

import hashlib
import json
import secrets
import shlex
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from hachi.models.chronos import ChronosModelPin
from hachi.models.chronos.inference import PREDICTION_FORMAT, REQUEST_FORMAT, canonical_bytes

INFERENCE_SCRIPT = "src/hachi/models/chronos/inference.py"
LOCAL_INFERENCE = Path(__file__).resolve().parents[1] / "models" / "chronos" / "inference.py"
GPU_BUSY = 75  # scripts/gx10/supervise.py: another compute process holds the GPU
SSH_FAILURE = 255
REMOTE_TIMEOUT = {124, 137}  # coreutils `timeout`: deadline reached, or killed after grace
# The GX10 enforces its own deadline this much before the local one, so a job still queued
# on the GPU lock ends there too instead of outliving the API's request.
REMOTE_MARGIN_SECONDS = 15


class GpuUnavailable(RuntimeError):
    """The GX10 or its GPU queue cannot run the job right now."""


class GpuTimeout(RuntimeError):
    """The job did not finish within its deadline."""


class GpuOutputRejected(RuntimeError):
    """The job's output failed identity or integrity checks."""


class GpuCleanupFailed(GpuOutputRejected):
    """Request or prediction files could not be removed from the GX10."""


class Transport(Protocol):
    """Remote operations on the GX10. SSH in production; a fake in tests."""

    def home(self) -> str: ...

    def write(self, path: str, data: bytes) -> None: ...

    def run(self, command: list[str], cwd: str, timeout: float) -> int: ...

    def read(self, path: str) -> bytes: ...

    def remove(self, path: str) -> None: ...


@dataclass(frozen=True)
class SshTransport:
    host: str
    connect_timeout: int = 10

    def _ssh(self, remote: str, *, data: bytes | None = None, timeout: float = 60) -> bytes:
        argv = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={self.connect_timeout}",
            self.host,
            remote,
        ]
        try:
            done = subprocess.run(argv, input=data, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise GpuTimeout("the GX10 did not answer in time") from exc
        except OSError as exc:
            raise GpuUnavailable("ssh is not available") from exc
        if done.returncode != 0:
            raise GpuUnavailable(f"remote step failed (exit {done.returncode})")
        return done.stdout

    def home(self) -> str:
        return self._ssh('printf %s "$HOME"').decode()

    def write(self, path: str, data: bytes) -> None:
        directory = str(Path(path).parent)
        self._ssh(
            f"umask 077 && mkdir -p {shlex.quote(directory)} && cat > {shlex.quote(path)}",
            data=data,
        )

    def run(self, command: list[str], cwd: str, timeout: float) -> int:
        deadline = max(1, int(timeout) - REMOTE_MARGIN_SECONDS)
        remote = f"cd {shlex.quote(cwd)} && timeout --kill-after=10 {deadline} " + " ".join(
            shlex.quote(a) for a in command
        )
        argv = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={self.connect_timeout}"]
        try:
            done = subprocess.run([*argv, self.host, remote], capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise GpuTimeout("the GPU job did not finish in time") from exc
        except OSError as exc:
            raise GpuUnavailable("ssh is not available") from exc
        return done.returncode

    def read(self, path: str) -> bytes:
        return self._ssh(f"cat {shlex.quote(path)}")

    def remove(self, path: str) -> None:
        self._ssh(f"rm -f {shlex.quote(path)}")


@dataclass(frozen=True)
class Gx10Target:
    """Where and as whom GPU jobs run. The checkout must hold #10's inference script."""

    transport: Transport
    owner: str
    checkout: str  # remote clone of a merged main commit
    timeout_seconds: float = 180.0


@dataclass(frozen=True)
class Quantiles:
    levels: tuple[float, ...]
    rows: tuple[tuple[float, ...], ...]  # horizon x levels, as the model produced them
    run_id: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chronos_quantiles(target: Gx10Target, pin: ChronosModelPin, row: dict) -> Quantiles:
    """Run one Chronos-2 context request on the GX10 and return its verified quantiles.

    The run id names no subject: GX10 job metadata stays free of identities.
    """
    request_bytes = canonical_bytes(row)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"api-chronos-{stamp}-{secrets.token_hex(4)}"
    home = target.transport.home().rstrip("/")
    workspace = f"{home}/hachi/workspaces/{target.owner}"
    request_path = f"{workspace}/state/api-requests/{run_id}.jsonl"
    run_dir = f"{home}/hachi/runs/{target.owner}/{run_id}"
    python = f"{workspace}/envs/{pin.runtime_lock_sha256[:16]}/bin/python"
    command = [
        "scripts/gx10/gpu-run",
        "--owner",
        target.owner,
        "--run-id",
        run_id,
        "--",
        python,
        "-I",
        INFERENCE_SCRIPT,
        "--requests",
        request_path,
        "--model",
        "infra/gx10/model.json",
        "--latency-samples",
        "0",
    ]
    outputs = (f"{run_dir}/predictions.jsonl", f"{run_dir}/inference.json")
    target.transport.write(request_path, request_bytes)
    failure: Exception | None = None
    try:
        code = target.transport.run(command, target.checkout, target.timeout_seconds)
        if code == GPU_BUSY:
            raise GpuUnavailable("the GX10 GPU is busy with another job")
        if code == SSH_FAILURE:
            raise GpuUnavailable("the GX10 could not be reached")
        if code in REMOTE_TIMEOUT:
            raise GpuTimeout("the GPU job did not finish in time (queue wait included)")
        if code != 0:
            raise GpuUnavailable(f"the GX10 job failed (exit {code})")
        predictions = target.transport.read(outputs[0])
        evidence_bytes = target.transport.read(outputs[1])
    except (GpuUnavailable, GpuTimeout) as exc:
        failure = exc
    # Remove everything this request put on the GX10, whatever happened above.
    stuck = []
    for path in (request_path, *outputs):
        try:
            target.transport.remove(path)
        except (GpuUnavailable, GpuTimeout):
            stuck.append(path.rsplit("/", 1)[-1])
    if stuck:
        raise GpuCleanupFailed(f"could not remove {', '.join(stuck)} from the GX10") from failure
    if failure is not None:
        raise failure
    return _verified(evidence_bytes, predictions, request_bytes, row, pin, run_id)


def _verified(
    evidence_bytes: bytes,
    predictions: bytes,
    request_bytes: bytes,
    row: dict,
    pin: ChronosModelPin,
    run_id: str,
) -> Quantiles:
    def reject(reason: str) -> GpuOutputRejected:
        return GpuOutputRejected(f"GX10 output rejected: {reason}")

    try:
        evidence = json.loads(evidence_bytes)
        lines = [json.loads(line) for line in predictions.splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise reject("unreadable output") from exc
    if evidence.get("format") != PREDICTION_FORMAT:
        raise reject("unexpected prediction format")
    if evidence.get("request_format") != REQUEST_FORMAT:
        raise reject("unexpected request format")
    model = evidence.get("model") or {}
    if evidence.get("weights_sha256") != pin.weights_sha256:
        raise reject("weights differ from the pin")
    if (model.get("model_id"), model.get("revision")) != (pin.model_id, pin.revision):
        raise reject("model revision differs from the pin")
    environment = evidence.get("environment") or {}
    if environment.get("script_sha256") != _sha256(LOCAL_INFERENCE.read_bytes()):
        raise reject("the GX10 ran a different inference script")
    if evidence.get("requests_sha256") != _sha256(request_bytes):
        raise reject("request checksum mismatch")
    if evidence.get("predictions_sha256") != _sha256(predictions):
        raise reject("prediction checksum mismatch")
    levels = evidence.get("quantile_levels")
    if not isinstance(levels, list) or not levels:
        raise reject("missing quantile levels")
    if len(lines) != 1 or lines[0].get("request_id") != row["request_id"]:
        raise reject("prediction does not answer this request")
    quantiles = lines[0].get("quantiles")
    if (
        not isinstance(quantiles, list)
        or len(quantiles) != row["prediction_length"]
        or any(not isinstance(step, list) or len(step) != len(levels) for step in quantiles)
    ):
        raise reject("prediction shape differs from the request")
    return Quantiles(
        levels=tuple(float(v) for v in levels),
        rows=tuple(tuple(float(v) for v in step) for step in quantiles),
        run_id=run_id,
    )
