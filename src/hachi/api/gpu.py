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

Nothing derived from the request outlives it on the GX10. After every job, successful or
not (including a failed write, an unreadable output or an unexpected error), the request
file and the job's whole run directory are removed. When the job's end is unknown (a local
timeout or a lost SSH session) its processes, found by the unique run id, are terminated
first, so nothing can be written after the removal. If termination or any removal cannot
be confirmed, `GpuCleanupFailed` withholds the forecast; failures are never suppressed.
"""

import hashlib
import json
import re
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

    def remove_tree(self, path: str) -> None: ...

    def terminate(self, marker: str) -> None:
        """Stop every process whose command line holds `marker`; raise unless none remain."""


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
        quoted = shlex.quote(path)
        self._ssh(f"rm -f -- {quoted} && ! test -e {quoted}")

    def remove_tree(self, path: str) -> None:
        quoted = shlex.quote(path)
        self._ssh(f"rm -rf -- {quoted} && ! test -e {quoted}")

    def terminate(self, marker: str) -> None:
        # "[a]pi-…" matches the job's command lines but not this shell's own, which holds
        # the bracketed spelling; the marker is letters, digits and '-' only.
        pattern = shlex.quote(f"[{marker[0]}]{marker[1:]}")
        self._ssh(
            f"pkill -TERM -f -- {pattern}; sleep 2; pkill -KILL -f -- {pattern}; sleep 1; "
            f"! pgrep -f -- {pattern} >/dev/null"
        )


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
    if not re.fullmatch(r"api-chronos-[0-9TZ]+-[0-9a-f]{8}", run_id):
        raise AssertionError("cleanup only ever targets this client's own run directory")
    failure: Exception | None = None
    ended = False  # the remote job reached a known end, so nothing more will be written
    try:
        target.transport.write(request_path, request_bytes)
        code = target.transport.run(command, target.checkout, target.timeout_seconds)
        ended = code != SSH_FAILURE
        if code == GPU_BUSY:
            raise GpuUnavailable("the GX10 GPU is busy with another job")
        if code == SSH_FAILURE:
            raise GpuUnavailable("the GX10 could not be reached")
        if code in REMOTE_TIMEOUT:
            raise GpuTimeout("the GPU job did not finish in time (queue wait included)")
        if code != 0:
            raise GpuUnavailable(f"the GX10 job failed (exit {code})")
        predictions = target.transport.read(f"{run_dir}/predictions.jsonl")
        evidence_bytes = target.transport.read(f"{run_dir}/inference.json")
    except Exception as exc:  # every failure still cleans up below, then is re-raised
        failure = exc
    stuck = _clean_up(target.transport, run_id, request_path, run_dir, terminate=not ended)
    if stuck:
        raise GpuCleanupFailed(f"could not confirm removal of {', '.join(stuck)}") from failure
    if failure is not None:
        raise failure
    return _verified(evidence_bytes, predictions, request_bytes, row, pin, run_id)


def _clean_up(
    transport: Transport, run_id: str, request_path: str, run_dir: str, *, terminate: bool
) -> list[str]:
    """Attempt every step even when one fails; return what could not be confirmed."""
    stuck = []
    if terminate:
        try:
            transport.terminate(run_id)
        except (GpuUnavailable, GpuTimeout):
            stuck.append("the remote job")
    for label, remove, path in (
        ("the request", transport.remove, request_path),
        ("the run directory", transport.remove_tree, run_dir),
    ):
        try:
            remove(path)
        except (GpuUnavailable, GpuTimeout):
            stuck.append(label)
    return stuck


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
