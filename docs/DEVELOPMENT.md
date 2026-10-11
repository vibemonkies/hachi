# Team and GX10 workflow

## Verified machine snapshot

Read-only SSH inspection on 2026-10-10 (America/Los_Angeles): `asus@100.108.229.115`, hostname `5ASB`, ARM64 Linux, NVIDIA GB10, driver 580.142, `nvidia-smi` reports CUDA compatibility 13.0, 121 GiB system memory, approximately 605 GB available disk, Python 3.12.3, Docker present. This does not verify an installed CUDA toolkit, working PyTorch GPU kernels, Docker permissions, or any model's ARM64 support. No training or environment changes were made during planning.

Connect using credentials shared privately by the team:

```sh
ssh asus@100.108.229.115
```

Never put the password, tokens, or personal exports in this repo, issues, shell examples, or recordings. Do not change credentials or system services as part of an experiment.

## Separate checkouts

Each person uses their own local clone and their own remote checkout, virtual environment/container, and local metadata database. Proposed remote layout (not provisioned yet):

```text
~/hachi/workspaces/ezzy1630/
~/hachi/workspaces/justin06lee/
~/hachi/workspaces/CoffeeCoder1015/
~/hachi/data/<dataset>/<version>/           immutable permitted source data
~/hachi/runs/<owner>/<run-id>/              outputs, logs, private metrics
~/hachi/artifacts/<artifact-id>/            immutable selected artifacts
~/hachi/coordination/gpu.lock               cooperative GPU lock
```

All three currently share the Unix account. Separate folders prevent accidental collisions but **do not provide privacy isolation**. Credentialed data may require every team member to be independently authorized; keep it off the shared account unless its agreement permits this arrangement. Use consented/public-permitted data for the shared demo.

## GPU ownership

The runtime issue implements a small cooperative wrapper using `flock` that holds one shared lock for the full job lifetime, writes owner/run/pid/start metadata, and releases on exit. Route training and GPU inference through that wrapper. Check `nvidia-smi` and existing processes; do not kill another person's job or remove a lock to jump the queue. CPU ingestion/UI work proceeds independently. Shared cache downloads must be atomic or separately locked.

Prove the runtime with a tensor operation **and** one forward/backward step of the intended model, then capture exact image digest or locked packages, architecture, GPU device, elapsed time, and peak memory where measurable. Test Mamba kernels explicitly for WBM; a successful import is insufficient. If WBM is blocked, preserve the failure and evaluate a compatible candidate while leaving the original gate visible. Do not overwrite the existing `~/venv`, `~/unsloth`, or unrelated installations.

## Branch and PR workflow

```sh
git clone https://github.com/vibemonkies/hachi.git
cd hachi
git switch main
git pull --ff-only
git switch -c issue-N-short-description
```

Commit focused changes, push your branch, and open a PR linked to the issue. One teammate reviews the artifact and reproduces the relevant command. Merge after the stated acceptance criteria pass. Do not change someone else's branch or shared working tree.

The issue assignee owns the listed files. Shared schemas, root dependency files, and CI changes require coordination before editing. Keep backend/data and modeling package dependencies in separate optional groups; let the contract owner integrate lockfile changes. Do not make all three people repeatedly resolve one giant environment.

## Status conventions

Use `status:ready`, `status:blocked`, `status:in-progress`, and `status:review` labels. Dependencies are explicit in each issue body. When a dependency lands, update the dependent issue to ready; labels do not update automatically. For external blockers, name the missing access/label/runtime and the owner who can resolve it. Never close required implementation work just because an alternative demo path exists.

At handoff, post commit/PR, reproducible command, artifact id, relevant result, and next blocker. Avoid participant-level data in comments. Keep milestone summaries about evidence, not percentage guesses.

## Demo operation

Default to a laptop-hosted UI and a backend reachable through a private SSH tunnel. Bind services to loopback unless exposure is deliberately authorized and configured. Use a separate metadata DB/ports per developer. A team-shared inference service must use frozen read-only artifacts and coordinate GPU access.

Use a saved result from a real, identified inference run for offline replay if the GPU/network fails, with a visible replay label and timestamp. It is not a live run. No paid provider, public deployment, or external upload is required by this plan.
