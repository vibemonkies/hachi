"""Run one foreground job while flock owns the shared GPU descriptor."""

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

OWNERS = ("ezzy1630", "justin06lee", "CoffeeCoder1015")


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True, choices=OWNERS)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", args.run_id):
        parser.error("run-id must be 1–96 letters, digits, dots, underscores or hyphens")
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("supply a foreground command after --")

    # Fail closed if telemetry fails or any non-Hachi compute process is active.
    # This is a preflight, not enforcement against programs bypassing this queue.
    active = subprocess.check_output(
        ["nvidia-smi", "--query-compute-apps=pid,process_name", "--format=csv,noheader"],
        text=True,
    ).strip()
    if active:
        print(f"GPU already has an unrelated compute process; leaving it alone:\n{active}", file=sys.stderr)
        return 75

    root = Path(os.environ["HACHI_HOME"]).resolve()
    workspace = root / "workspaces" / args.owner
    if not workspace.is_dir():
        parser.error(f"owner workspace is not provisioned: {workspace}")
    run = root / "runs" / args.owner / args.run_id
    run.parent.mkdir(parents=True, exist_ok=True)
    run.mkdir()  # A run id is immutable; never overwrite an earlier job.
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update(
        HACHI_OWNER=args.owner,
        HACHI_RUN_DIR=str(run),
        HACHI_DB_PATH=str(workspace / "state" / "metadata.sqlite3"),
        HF_HOME=str(workspace / "cache" / "huggingface"),
        XDG_CACHE_HOME=str(workspace / "cache"),
        CUDA_VISIBLE_DEVICES="0",
        OMP_NUM_THREADS="4",
        TOKENIZERS_PARALLELISM="false",
        HF_HUB_DISABLE_TELEMETRY="1",
        PYTHONNOUSERSITE="1",
    )
    current = root / "coordination" / "current.json"
    metadata = {
        "owner": args.owner, "run_id": args.run_id, "supervisor_pid": os.getpid(),
        "queued_at": env["HACHI_QUEUED_AT"], "started_at": now(),
        "run_directory": str(run), "state": "starting",
    }
    # Do not record command arguments: they may contain private data or tokens.
    write_json(current, metadata)
    started = time.monotonic()
    child = None
    received_signal = None

    def forward_signal(number, _frame):
        nonlocal received_signal
        received_signal = number
        if child is not None:
            try:
                os.killpg(child.pid, number)
            except ProcessLookupError:
                pass

    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(number, forward_signal)
    code = 1
    try:
        with (run / "output.log").open("xb") as output:
            # The inherited flock descriptor keeps the GPU reserved even if this
            # supervisor is SIGKILLed while the foreground job is still running.
            child = subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT,
                                     start_new_session=True, close_fds=False)
            metadata.update(job_pid=child.pid, state="running")
            write_json(current, metadata)
            if received_signal is not None:
                forward_signal(received_signal, None)
            code = child.wait()
            if received_signal is not None:
                code = 128 + received_signal
            elif code < 0:
                code = 128 - code
    finally:
        metadata.update(state="finished", ended_at=now(), exit_code=code,
                        elapsed_seconds=time.monotonic() - started)
        write_json(run / "job.json", metadata)
        current.unlink(missing_ok=True)
    print(f"Hachi job exited {code}; logs: {run}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
