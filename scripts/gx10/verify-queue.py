"""Exercise actual Linux flock contention, failures, signals, and GPU preflight."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


def until(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise TimeoutError("queue verification condition was not reached")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu-python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wrapper = Path(__file__).with_name("gpu-run").resolve()
    processes = []
    checks = []
    with tempfile.TemporaryDirectory(prefix="hachi-queue-") as directory:
        root = Path(directory)
        for owner in ("ezzy1630", "justin06lee"):
            (root / "workspaces" / owner).mkdir(parents=True)
        env = {**os.environ, "HACHI_HOME": str(root)}

        def launch(owner, run_id, code):
            process = subprocess.Popen([str(wrapper), "--owner", owner, "--run-id", run_id,
                                        "--", sys.executable, "-c", code], env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(process)
            return process

        def record(owner, run_id):
            return json.loads((root / "runs" / owner / run_id / "job.json").read_text())

        def wait_running(run_id):
            def running():
                current = root / "coordination/current.json"
                if not current.exists():
                    return False
                metadata = json.loads(current.read_text())
                return metadata["run_id"] == run_id and metadata["state"] == "running"
            until(running)

        try:
            first = launch("ezzy1630", "first", "import time; time.sleep(1.5)")
            wait_running("first")
            second = launch("justin06lee", "second", "print('second entered')")
            time.sleep(0.3)
            assert second.poll() is None, "second job did not wait"
            assert not (root / "runs/justin06lee/second").exists(), "second entered while first held lock"
            assert first.wait(timeout=10) == 0 and second.wait(timeout=10) == 0
            a, b = record("ezzy1630", "first"), record("justin06lee", "second")
            assert datetime.fromisoformat(b["started_at"]) >= datetime.fromisoformat(a["ended_at"])
            checks.append({"check": "two_owners_serialize", "passed": True,
                           "first_seconds": a["elapsed_seconds"], "second_started_after_first_ended": True})

            failed = launch("ezzy1630", "failed", "raise SystemExit(7)")
            assert failed.wait(timeout=10) == 7
            assert record("ezzy1630", "failed")["exit_code"] == 7
            following = launch("justin06lee", "after-error", "pass")
            assert following.wait(timeout=10) == 0
            checks.append({"check": "error_exit_releases_lock_and_preserves_status", "passed": True})

            terminated = launch("ezzy1630", "terminated", "import time; time.sleep(30)")
            wait_running("terminated")
            terminated.send_signal(signal.SIGTERM)
            assert terminated.wait(timeout=10) == 143
            assert record("ezzy1630", "terminated")["exit_code"] == 143
            following = launch("justin06lee", "after-term", "pass")
            assert following.wait(timeout=10) == 0
            checks.append({"check": "sigterm_forwards_to_job_before_unlock", "passed": True})

            killed = launch("ezzy1630", "killed", "import time; time.sleep(1.5)")
            wait_running("killed")
            killed.kill()
            assert killed.wait(timeout=10) == -signal.SIGKILL
            following = launch("justin06lee", "after-kill", "pass")
            time.sleep(0.3)
            assert following.poll() is None, "SIGKILL unlocked while child still ran"
            assert not (root / "runs/justin06lee/after-kill").exists()
            assert following.wait(timeout=10) == 0
            checks.append({"check": "sigkill_keeps_lock_in_live_child", "passed": True})

            # This is our own short-lived CUDA process, deliberately outside the
            # queue. Only this PID is stopped; existing machine jobs are untouched.
            ready = root / "cuda-ready"
            blocker = subprocess.Popen([str(args.gpu_python), "-c",
                "import pathlib,sys,time,torch; x=torch.ones(1,device='cuda'); "
                "torch.cuda.synchronize(); pathlib.Path(sys.argv[1]).touch(); time.sleep(30)", str(ready)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            processes.append(blocker)
            until(lambda: ready.exists() or blocker.poll() is not None)
            assert ready.exists(), blocker.stderr.read().decode()
            rejected = launch("justin06lee", "external-busy", "raise SystemExit('must not enter')")
            assert rejected.wait(timeout=10) == 75
            assert not (root / "runs/justin06lee/external-busy").exists()
            blocker.terminate()
            blocker.wait(timeout=10)
            following = launch("ezzy1630", "after-external", "pass")
            assert following.wait(timeout=10) == 0
            checks.append({"check": "uncoordinated_cuda_job_refused_without_interference", "passed": True})

            duplicate = launch("ezzy1630", "first", "pass")
            assert duplicate.wait(timeout=10) != 0
            assert record("ezzy1630", "first") == a
            checks.append({"check": "duplicate_run_id_cannot_overwrite", "passed": True})
            assert not (root / "coordination/current.json").exists()
            # The lock inode survives all exits and is never removed by cleanup.
            assert (root / "coordination/gpu.lock").exists()
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
    evidence = {"status": "passed", "mechanism": "actual Linux flock; real CUDA preflight",
                "independent_teammate_rerun": False, "checks": checks}
    source = wrapper.parents[2]
    evidence["source_base_commit"] = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    evidence["source_sha256"] = {
        str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (wrapper, wrapper.with_name("supervise.py"), Path(__file__).resolve())
    }
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
