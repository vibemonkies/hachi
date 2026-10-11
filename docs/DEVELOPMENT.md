# Team and GX10 workflow

## Verified machine snapshot

Issue #1 setup targets `asus@100.108.229.115`, hostname `5ASB`. Live inspection on 2026-10-10 (America/Los_Angeles): Ubuntu 24.04.4, kernel `6.17.0-1014-nvidia`, ARM64, NVIDIA GB10, driver `580.142`, installed toolkit `nvcc 13.0.88`, Python `3.12.3`, 121 GiB system memory, initially 605 GiB free on `/`. The system toolkit is distinct from the CUDA libraries in our pinned PyTorch wheels. Docker is installed but `asus` cannot access its socket; this setup uses isolated venvs without changing permissions.

Connect using credentials shared privately by the team:

```sh
ssh asus@100.108.229.115
```

Never put the password, tokens, or personal exports in this repo, issues, shell examples, or recordings. Do not change credentials or system services as part of an experiment.

## Separate checkouts

Each person uses their own local clone and their own remote checkout, virtual environment, cache, and metadata database path. The provisioner creates this layout:

```text
~/hachi/workspaces/<owner>/hachi/           owner checkout
~/hachi/workspaces/<owner>/envs/<lock-id>/  owner environment
~/hachi/workspaces/<owner>/cache/          owner model/download cache
~/hachi/workspaces/<owner>/state/metadata.sqlite3
~/hachi/infra/wheels/<full-lock-sha>/       verified, reusable wheels
~/hachi/data/<dataset>/<version>/           immutable permitted source data
~/hachi/runs/<owner>/<run-id>/              outputs, logs, private metrics
~/hachi/artifacts/<artifact-id>/            immutable selected artifacts
~/hachi/coordination/gpu.lock               cooperative GPU lock
```

All three currently share the Unix account. Separate folders prevent accidental collisions but **do not provide privacy isolation**. Credentialed data may require every team member to be independently authorized; keep it off the shared account unless its agreement permits this arrangement. Use consented/public-permitted data for the shared demo.

## GPU ownership

Use `scripts/gx10/gpu-run` for all Hachi GPU work. It waits on `~/hachi/coordination/gpu.lock`, records owner/run/supervisor PID/job PID/start/end/exit status, and releases after the foreground job exits. `flock --no-fork` and an inherited descriptor retain the lock if the supervisor is killed while the child still runs. Signals are forwarded to the job process group. Run IDs cannot be reused. Never delete the lock file: doing so creates a different inode and defeats coordination. `current.json` is advisory and can be stale after SIGKILL; actual lock ownership is authoritative.

After acquiring the lock, the wrapper refuses to run if `nvidia-smi` finds another compute process (exit 75), or if GPU telemetry fails. It never kills an existing workload. This is cooperative coordination, not a machine-wide scheduler: programs bypassing the wrapper can start after its preflight. Foreground commands must not daemonize or deliberately close the inherited lock descriptor. Logs and `job.json` go to `~/hachi/runs/<owner>/<run-id>/`; command arguments are deliberately omitted from metadata. CPU ingestion/UI work proceeds independently. Wheel provisioning has a separate lock and atomic checksum-verified downloads; model caches are per owner.

The runtime pins the self-contained ARM64 PyTorch `2.8.0+cu129` wheel (bundled CUDA 12.9), Chronos `2.3.2`, Transformers `4.57.6`, all transitive wheels with SHA-256, and `amazon/chronos-2` revision `29ec3766d36d6f73f0696f85560a422f50e8498c` with a weight checksum. See [the runtime manifest](../infra/gx10/README.md) for exact setup, verification, timings and handoff. The check runs CUDA matrix multiplication, public model inference, and a forward/backward/optimizer update on synthetic data. It establishes execution compatibility, not physiological accuracy or a trained Hachi model.

WBM/Mamba kernels are not attempted by this setup and remain a separate admission gate. No existing `~/venv`, `~/unsloth`, machine packages, shell startup files, credentials, Ollama settings, or unrelated services are modified.

Prove the runtime with a tensor operation **and** one forward/backward step of the intended model, then capture exact image digest or locked packages, architecture, GPU device, elapsed time, and peak memory where measurable. Test Mamba kernels explicitly for WBM; a successful import is insufficient. If WBM is blocked, preserve the failure and evaluate a compatible candidate while leaving the original gate visible. Do not overwrite the existing `~/venv`, `~/unsloth`, or unrelated installations.

## Local toolchain

Python 3.12 (matching the GX10) is pinned in `.python-version` and installed by uv; `uv.lock` pins every Python package. The `contracts/` package uses bun, with `contracts/bun.lock`. From the repository root:

| Command | Effect |
|---|---|
| `make` | `setup`, `build` and `check` in one go |
| `make setup` | Install the locked Python and bun environments |
| `make build` | Regenerate `contracts/schema`, `contracts/typescript` and `contracts/fixtures` from `src/hachi/contracts` |
| `make check` | Ruff on `src/`, `tests/` and `contracts/`, pytest, the coordination script's tests, and checks that every generated file is current; CI runs this on every push |

Never edit generated contract files by hand. Change the models in `src/hachi/contracts/` (or fixture definitions in `contracts/scripts/build_fixtures.py`), run `make build`, and commit the source and generated files together.

The base install and the `dev` group are CPU-only. Lane dependencies go in optional groups (`uv add --optional data …`, `--optional api …`, `--optional baselines …`, `--optional models …`). The `baselines` extra contains CPU tree fitting and is exercised separately in CI. GPU/foundation-model packages belong in `models` or the isolated GX10 runtime lock; CPU baseline CI does not install those environments.

## Branch and PR workflow

```sh
git clone https://github.com/vibemonkies/hachi.git
cd hachi
git switch main
git pull --ff-only
git switch -c issue-N-short-description
```

Commit focused changes, push your branch, and open a PR linked to the issue. Verify the artifact with the relevant command and record the result. Merge after the stated acceptance criteria pass. Do not change someone else's branch or shared working tree.

The issue assignee owns the listed files. Shared schemas, root dependency files, and CI changes require coordination before editing. Keep backend/data and modeling package dependencies in separate optional groups; let the contract owner integrate lockfile changes. Do not make all three people repeatedly resolve one giant environment.

## Setup and run

From a checkout containing the runtime files on the GX10:

```sh
# One owner at a time. A provisioned checkout is never pulled/reset/overwritten.
scripts/gx10/provision ezzy1630 --source https://github.com/vibemonkies/hachi.git
scripts/gx10/provision justin06lee --source https://github.com/vibemonkies/hachi.git
scripts/gx10/provision CoffeeCoder1015 --source https://github.com/vibemonkies/hachi.git
```

Private repository cloning requires your existing GitHub authorization. If unavailable on the GX10, create `git bundle create hachi.bundle <branch>` on a machine with the intended committed branch and transfer the bundle via SCP; pass its absolute path to `--source` and the named branch to `--branch` (default `main`). A bundle may omit symbolic HEAD, so the provisioner explicitly selects the branch. Do not transfer GitHub credentials. The initial issue #1 live verification used a bundle of `a7e44d2` plus the then-uncommitted runtime file snapshot. The PR publishes that tested code; existing remote snapshots are updated only by their owners.

Run from your own remote checkout:

```sh
owner=ezzy1630  # or justin06lee / CoffeeCoder1015
cd "$HOME/hachi/workspaces/$owner/hachi"
lock_id=$(sha256sum infra/gx10/requirements.lock | cut -c1-16)
runtime_py="$HOME/hachi/workspaces/$owner/envs/$lock_id/bin/python"
scripts/gx10/gpu-run --owner "$owner" --run-id "runtime-$(date -u +%Y%m%dT%H%M%SZ)" \
  -- "$runtime_py" scripts/gx10/verify-runtime.py
```

`verify-runtime.py` is also the exact synthetic inference command; it additionally proves gradients and an optimizer update without saving modified weights. Each run produces `runtime.json`, `job.json`, and `output.log` outside Git. Invoke other GPU scripts through the same wrapper and interpreter. `HACHI_DB_PATH`, `HF_HOME`, `XDG_CACHE_HOME`, `HACHI_OWNER`, and `HACHI_RUN_DIR` are set for the selected owner. The placeholder SQLite file has no application schema; migrations remain the backend owner's responsibility.

Queue lifecycle verification (run while the GPU is idle):

```sh
python3 scripts/gx10/verify-queue.py --gpu-python "$runtime_py" \
  --output "$HOME/hachi/infra/queue-verification.json"
```

This test uses disposable coordination folders and real `flock`, checks two owners, failure/termination/SIGKILL, reused run IDs, and a short-lived CUDA process created by the test to verify refusal of unrelated compute. It stops only its own processes. It simulates a second caller. Verify the results and record the commands and environment identity for the issue's handoff gate.

## Status conventions

Use `status:ready`, `status:blocked`, `status:in-progress`, and `status:review` labels. Dependencies are explicit in each issue body. When a dependency lands, update the dependent issue to ready; labels do not update automatically. For external blockers, name the missing access/label/runtime and the owner who can resolve it. Never close required implementation work just because an alternative demo path exists.

At handoff, post commit/PR, reproducible command, artifact id, relevant result, and next blocker. Avoid participant-level data in comments. Keep milestone summaries about evidence, not percentage guesses.

## Demo operation

Default to a laptop-hosted UI and a backend reachable through a private SSH tunnel. Bind services to loopback unless exposure is deliberately authorized and configured. Use a separate metadata DB/ports per developer. A team-shared inference service must use frozen read-only artifacts and coordinate GPU access.

Use a saved result from a real, identified inference run for offline replay if the GPU/network fails, with a visible replay label and timestamp. It is not a live run. No paid provider, public deployment, or external upload is required by this plan.
