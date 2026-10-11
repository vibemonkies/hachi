# GX10 encoder runtime (#11): WBM (Mamba2) and MOMENT on GB10

This is a separate, hash-locked environment for the #11 frozen encoders. It sits beside the #1 runtime: [`../requirements.lock`](../requirements.lock) and the `envs/8e30ab7405c3087d` environments are untouched. The system CUDA 13.0 toolkit, `~/venv`, `~/unsloth` and all system packages are also untouched. Everything this builds lives in the owner's workspace.

## Identity

- **Machine:** GX10 `5ASB`, NVIDIA GB10 (compute capability 12.1), driver 580.142, Linux 6.17.0-1014-nvidia aarch64, system CPython 3.12.3.
- **Environment:** `~/hachi/workspaces/justin06lee/envs/ea5d6c71db9ca4a6`.
  - The id is `sha256(requirements.lock + built.lock)` = `ea5d6c71db9ca4a68de2229406517cbb32f608f0c1dcff13ee96b3aa5b991baf`.
  - `pip check` is clean.
  - The installed set is in [`evidence/2026-10-11/environment.json`](evidence/2026-10-11/environment.json).
- **Locked wheels:** [`requirements.lock`](requirements.lock), sha256 `1fd83f4b…9ee5`, resolved from [`runtime.in`](runtime.in).
  - torch 2.8.0+cu129 and Triton 3.4.0: the same self-contained ARM64 wheels as #1.
  - transformers 4.57.6 and numpy 2.5.4.
  - Every wheel's URL and SHA-256 is in [`wheels.json`](wheels.json).
- **Local builds:** [`built.lock`](built.lock) pins the exact wheels built here. Receipts are in [`evidence/2026-10-11/built-wheels-blackwell.json`](evidence/2026-10-11/built-wheels-blackwell.json).
  - causal-conv1d 1.5.0.post8 from `Dao-AILab/causal-conv1d@82867a9` (tag v1.5.0.post8).
  - mamba-ssm 2.2.4 from `state-spaces/mamba@95d8aba` (tag v2.2.4). This is the version OpenMHC builds WBM against.
  - momentfm 0.1.5 from `moment-timeseries-foundation-model/moment@38f7310`.
- **Build toolchain:** NVIDIA's CUDA 12.9.1 `linux-sbsa` redistributables. Each archive is SHA-256-checked against `redistrib_12.9.1.json` (component list in [`sources.json`](sources.json)), unpacked into `~/hachi/workspaces/<owner>/toolchains/cuda-12.9.1-linux-sbsa/`.
  - torch refuses to build extensions with a different CUDA major than its own 12.9.
  - nvcc 12.9.86 targets `compute_121`.
- **Kernel targets:** the upstream gencode list (sm_53–sm_90) plus `NVCC_APPEND_FLAGS="-gencode arch=compute_120,code=sm_120 -gencode arch=compute_121,code=sm_121 -gencode arch=compute_121,code=compute_121"`. The sources themselves are unmodified.

## Reproduce

Run from an owner clone on the GX10, made from a bundle of this branch:

```sh
# CPU only, no GPU lock: verified toolchain and headers, builder venv, wheels (about 20 min).
python3 infra/gx10/encoders/build.py --owner justin06lee --variant blackwell
# New environment from requirements.lock + built.lock; the build output's built.lock must match.
python3 infra/gx10/encoders/provision.py --owner justin06lee \
  --built ~/hachi/workspaces/justin06lee/built-wheels/blackwell-<timestamp>
py=~/hachi/workspaces/justin06lee/envs/ea5d6c71db9ca4a6/bin/python
g=src/hachi/models/encoders/gx10
scripts/gx10/gpu-run --owner justin06lee --run-id issue11-kernels-$(date -u +%Y%m%dT%H%M%SZ) -- $py $g/verify_kernels.py
scripts/gx10/gpu-run --owner justin06lee --run-id issue11-wbm-proof-... -- $py $g/embed.py wbm --config configs/models/encoders/wbm.json --prove
scripts/gx10/gpu-run --owner justin06lee --run-id issue11-moment-proof-... -- $py $g/embed.py moment --config configs/models/encoders/moment.json --prove
```

Local wheel builds are not byte-reproducible. A rebuild elsewhere gets new wheel hashes, a new `built.lock` and so a new environment id, and it needs fresh GPU evidence.

## Two runtime prerequisites, set automatically

- **Python headers.** Triton JIT-compiles a C launcher with gcc the first time a kernel runs, and that needs `Python.h`, which the GX10's interpreter does not ship. `build.py` runs `apt-get download` for `libpython3.12-dev` (no root), checks it against the SHA256 in apt's signed index and unpacks it into the owner workspace. The GX10 scripts point `CPATH` at that tree.
  - The interpreter is 3.12.3-1ubuntu0.13; the only candidate headers are 3.12.3-1ubuntu0.17.
  - Bugfix revisions of 3.12.3 share one C ABI.
- **ptxas.** Triton 3.4 bundles ptxas 12.8, which rejects `sm_121a`. The scripts set `TRITON_PTXAS_PATH` to the verified toolchain's ptxas 12.9.

Both paths are recorded in every kernel and embedding receipt.

## What failed, and what replaced it

Every failure has a log on the GX10 and a summary in `evidence/2026-10-11/`.

| Attempt | Failure | Evidence | Replacement |
|---|---|---|---|
| PyPI sdists `causal_conv1d-1.5.0.post8.tar.gz`, `mamba_ssm-2.2.4.tar.gz` | They contain no `csrc/`; ninja: `csrc/causal_conv1d.cpp ... missing`. They only fetch prebuilt GitHub wheels, and none exist for aarch64 | `build-failures.json` (attempt 1) | Build from the release-tag commits |
| First source build | `fatal error: Python.h: No such file or directory` | `build-failures.json` (attempt 2) | Verified `libpython3.12-dev` headers in the owner workspace |
| Upstream build, sm_53–sm_90 only | Import works; launch fails on GB10: `CUDA error: no kernel image is available for execution on the device` | `kernel-image-probe-upstream.json` | Append sm_120/sm_121 SASS and compute_121 PTX (`kernel-image-probe-blackwell.json`: runs, finite) |
| First GPU proof | CUDA extensions passed; every Triton kernel failed compiling its launcher (`Python.h`) | `kernels-attempt1-no-python-headers.json` | `CPATH` to the verified headers |
| Second GPU proof | `ptxas fatal: Value 'sm_121a' is not defined for option 'gpu-name'` | `kernels-attempt2-ptxas-sm121a.json` | `TRITON_PTXAS_PATH` to the CUDA 12.9.1 ptxas |

## GPU evidence

Every job ran through `scripts/gx10/gpu-run --owner justin06lee`. Job timestamps and exit codes are in `evidence/2026-10-11/jobs.json`.

- **Kernels** (`kernels.json`, run `issue11-kernels-20261011T120254Z`): every case compares the compiled or Triton kernel with the PyTorch reference shipped in the same package, on seeded random tensors in float32 with TF32 off. Tolerances are forward 2e-3 and gradient 1e-2, as the largest relative error. Peak CUDA allocation was 364 MiB.

  | Case | Shape | Forward rel. error | Worst gradient rel. error |
  |---|---|---|---|
  | `causal_conv1d_cuda` vs `causal_conv1d_ref` | 2×768×168 | 6.9e-8 | 2.0e-7 |
  | `selective_scan_cuda` vs `selective_scan_ref` | 2×64×168 | 1.3e-6 | 1.7e-6 |
  | Triton SSD `mamba_chunk_scan_combined` vs `ssd_chunk_scan_combined_ref` | 2×512×8×64 | 1.4e-3 | 1.7e-3 |
  | Fused `mamba_split_conv1d_scan_combined` vs `mamba_split_conv1d_scan_ref`, WBM's Mamba2 shape (d_model 256) | 2×168×256 | 2.7e-4 | 1.8e-3 |
  | `Mamba2` module, fused vs unfused kernel paths | 2×168×256 | 0 | 0 |

- **WBM model** (`wbm-proof.json`): the pinned checkpoint, loaded with `weights_only=True`. Its pickle references only `OrderedDict`, `FloatStorage` and `_rebuild_tensor_v2`. No keys are missing or unexpected; the projection head is linear; 6,405,120 parameters.
  - Two synthetic forward/backward/SGD steps on unfrozen weights: output 4×256, finite loss (0.1205, then 0.1178) and finite gradients. 100 of 110 tensors moved.
  - The projection head receives no gradient by design: the loss is on the 256-d representation `r`.
  - Eight `dt_bias` updates fall below float32 resolution at lr 1e-3. They are listed by name.
  - Timing: 12.0 s for the first step (it includes Triton JIT), 41 ms warm. Peak CUDA allocation 424 MiB.
- **MOMENT model** (`moment-proof.json`): MOMENT-1-large at its pinned revision, from safetensors.
  - Output 4×1024, finite loss and gradients. 219 of 221 tensors moved.
  - T5's unused token embedding gets no gradient. The patch mask embedding gets an exact zero gradient, because every step is observed.
  - Timing: 196 ms warm. Peak CUDA allocation 4,055 MiB.
- **Embeddings** (`embed-wbm.json`, `embed-moment.json`): 2,143 PMData windows, inputs sha256 `63cb2622…`.
  - WBM: five input variants, each 2,143×256, all finite. A rerun differs by 0.0. 35 s; 456 MiB.
  - MOMENT: 2,143×5,120 (5 channels × 1,024), all finite. A rerun differs by 0.0. 132 s; 1,659 MiB.

PyTorch 2.8 still warns that its compiled architectures end at sm_120. The operations above were tested on the device, but this evidence does not certify every PyTorch kernel, `torch.compile`, BF16 or large batches.

## Storage

- **Toolchain, headers, builder venvs, build logs and built wheels:** `~/hachi/workspaces/justin06lee/{toolchains,build-venvs,built-wheels}/`.
- **Locked runtime wheels:** `~/hachi/infra/wheels/1fd83f4b…/`.
- **Checkpoints:** the owner HF cache, `~/hachi/workspaces/justin06lee/cache/huggingface/`.
- **Runs:** `~/hachi/runs/justin06lee/issue11-*`.

Model weights and embeddings never enter Git.
