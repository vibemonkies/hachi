# GX10 runtime — issue #1

Scope: isolated owner checkouts/environments, a cooperative GPU lock, and synthetic execution proof for the project's first pretrained candidate. No health dataset, trained Hachi artifact, API service, or predictive accuracy is implied.

## Environment identity

- Target: `asus@100.108.229.115`, hostname `5ASB`, NVIDIA GB10, compute capability `12.1`.
- OS: Ubuntu `24.04.4`; kernel `6.17.0-1014-nvidia`; installed system toolkit `13.0.88`; driver `580.142`.
- Runtime: CPython `3.12.3`, PyTorch `2.8.0+cu129` with bundled CUDA `12.9`, Triton `3.4.0`, Chronos `2.3.2`, Transformers `4.57.6`.
- Package lock SHA-256: `8e30ab7405c3087d73bc489dbdcb3912cba2298f1a2fd4b7fda57b1548ab5f8a`.
- Model: `amazon/chronos-2`, revision `29ec3766d36d6f73f0696f85560a422f50e8498c`, weight SHA-256 `ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42`.
- Live verification used base `a7e44d225229d77c9663c65c966dcd053a582fed` with the then-uncommitted runtime snapshot on branch `issue-1-gx10-runtime`. The PR packages the same tested runtime code, identified by file hashes in the evidence; documentation was updated for publication. Remote checkouts retain their original validation snapshots until their owners choose to update them.
- Disk after provisioning/cleanup: approximately **582 GiB available**, recorded in `machine.json` (initially 605 GiB). Environments, public checkpoint caches and the reusable wheelhouse occupy the new Hachi tree.

[`runtime.in`](runtime.in) records the selected inputs. [`requirements.lock`](requirements.lock) pins every package and hash; [`wheels.json`](wheels.json) pins each exact download URL and artifact hash. Installs use only verified wheels, `--no-index`, `--no-deps`, `--require-hashes`, then `pip check`. The system driver/toolkit and existing machine environments are never changed.

The [official PyTorch wheel index](https://download.pytorch.org/whl/cu129/torch/) supplies the self-contained ARM64 build; the [official Triton index](https://download.pytorch.org/whl/cu129/triton/) supplies the ARM64 wheel absent from PyPI for this version. Chronos usage and checkpoint terms come from the [official package](https://github.com/amazon-science/chronos-forecasting) and [model card](https://huggingface.co/amazon/chronos-2).

## Provisioning

See [the development workflow](../../docs/DEVELOPMENT.md#setup-and-run) for exact owner commands. The installed interpreters are:

```text
/home/asus/hachi/workspaces/ezzy1630/envs/8e30ab7405c3087d/bin/python
/home/asus/hachi/workspaces/justin06lee/envs/8e30ab7405c3087d/bin/python
/home/asus/hachi/workspaces/CoffeeCoder1015/envs/8e30ab7405c3087d/bin/python
```

Each owner has `hachi/`, `envs/`, `cache/`, and `state/metadata.sqlite3`. The SQLite file is an empty placeholder with `user_version=0`; backend migrations own its schema. Checkouts start from the same named source branch. An existing checkout is never updated or reset; an unexpected origin or unrecognized environment causes refusal. A complete matching environment is checked and reused. A failed newly created environment is removed by its creating invocation.

For the initial transfer, a bundle of `main` supplied the committed base, and only the owned runtime paths plus `docs/DEVELOPMENT.md` were copied into newly created checkouts. Nothing was copied into a pre-existing teammate checkout. Future transfers should bundle the reviewed committed branch and pass `--branch <branch>` explicitly. GitHub authorization is required only for a direct private clone; no credential transfer or account changes are part of provisioning.

Regenerate the lock on the GX10 in a disposable, project-owned venv:

```sh
python3 -m venv "$HOME/hachi/infra/lock-builder/.venv"
builder="$HOME/hachi/infra/lock-builder/.venv/bin/python"
"$builder" -m pip --isolated install pip==25.2
"$builder" -m pip --isolated install --dry-run --ignore-installed --only-binary=:all: \
  --report "$HOME/hachi/infra/resolution.json" -r infra/gx10/runtime.in
python3 scripts/gx10/lock-from-report.py "$HOME/hachi/infra/resolution.json" infra/gx10
```

Resolution is intentionally an explicit maintenance operation. Normal provisioning never resolves newer dependencies or edits the lock. New resolutions must receive new GPU/model evidence. The initial lock combines the report from all final inputs on this exact ARM64 host; failed candidate locks/environments are removed after verification.

## Live evidence

[`evidence/2026-10-11/`](evidence/2026-10-11/) contains sanitized machine identity, package/source identities, per-owner results and job timestamps, and real Linux queue checks. All runtime inputs are a generated sine wave, with batch size one, context length 128, and horizon 16. The public forecasting pipeline receives CPU inputs and moves batches to its CUDA model; direct training receives CUDA tensors. No private exports or participant measurements are used.

Ezzy's measured run produced prediction shape `[1, 21, 16]`, finite loss/gradients, and changed output-layer weights after an SGD step. Representative warm inference was **13.5 ms**; forward/backward/optimizer update **173.6 ms**; peak allocated CUDA memory **950.6 MiB**, reserved **1014 MiB**, peak process RSS approximately **1.65 GiB**. These are one-run synthetic measurements, not throughput benchmarks or clinical evaluation. Full timestamps and timings, including download/startup, are in `runtime-<owner>.json` and `job-<owner>.json`. GB10 uses unified memory, so allocator counts do not measure all machine/GPU memory.

All three owner environments passed the full synthetic GPU/model check and `pip check`. The queue verifier checks two owners, error exit status, SIGTERM forwarding, SIGKILL while the child still holds the lock, refusal of a real CUDA process outside the queue, and rejection of duplicate run IDs. It uses a disposable coordination directory and stops only its own processes. Per-owner model commands also go through the actual shared Hachi lock: CoffeeCoder's run waited approximately 21 seconds behind Justin's, then began after Justin exited (`shared-contention.json`). Agent execution in these three directories remains distinct from independent teammate reproduction.

## Storage and ports

- Run logs/results: `~/hachi/runs/<owner>/<run-id>/` (`runtime.json`, `job.json`, `output.log`).
- Public pretrained weights: `~/hachi/workspaces/<owner>/cache/huggingface/`; they remain outside Git.
- Verified wheelhouse: `~/hachi/infra/wheels/<full-lock-sha>/`; provisioning is separately locked.
- Immutable selected artifacts: reserved for `~/hachi/artifacts/<artifact-id>/`; this issue does not publish a selected model artifact.
- Live lock: `~/hachi/coordination/gpu.lock`; advisory current metadata: `current.json`. Never delete the lock file. After SIGKILL, metadata may be stale until the next holder replaces it.

This issue launches no network service and takes no listening port. For future backend work, proposed loopback ports are Ezzy `8001`, Justin `8002`, CoffeeCoder `8003`; each owner must check `ss -lntp` before binding. Example private tunnel after Justin starts his separately authorized backend on `127.0.0.1:8002`:

```sh
ssh -N -o ExitOnForwardFailure=yes -L 18002:127.0.0.1:8002 asus@100.108.229.115
```

Then use `http://127.0.0.1:18002` locally. No API exists from issue #1 alone. Ollama's existing loopback port `11434` and other machine services are untouched.

## Compatibility limits and handoff

The cu130 candidate failed `pip check`: `nvidia-cusparselt-cu13 0.8.0 is not supported on this platform`. Both PyPI and NVIDIA-hosted ARM64-named wheels contain the internal `manylinux2014_sbsa` tag, including inspected cu13 `0.8.1` and cu12 `0.7.1`. The final self-contained PyTorch build avoids those external packages. No metadata edit, ignored dependency, or weakened check is used. See [`compatibility.json`](evidence/compatibility.json).

PyTorch 2.8 reports a capability warning: its compiled architectures end at `sm_120`, while GB10 reports `12.1`. The actual selected tensor, inference, and training operations are tested on that device. The warning remains visible in logs; this evidence does not certify every PyTorch/custom CUDA kernel, `torch.compile`, BF16, large batches, or WBM/Mamba. WBM kernels are not attempted and retain their separate admission gate.

The GPU lock is cooperative. Programs bypassing it can start after preflight; it does not control Ollama or other teams' workloads. Foreground jobs must not daemonize or close their inherited lock descriptor. All contributors share Unix account `asus`, so separate folders provide collision prevention, not privacy isolation.

Before closing issue #1, a real teammate must independently rerun the pinned GPU verification and show that a second job waits. Agent execution under another owner directory is not independent teammate reproduction. The implementation and sanitized evidence are ready for review; keep the issue open until that handoff gate passes.
