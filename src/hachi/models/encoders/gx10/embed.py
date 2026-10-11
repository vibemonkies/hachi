"""Frozen WBM / MOMENT embeddings on the GX10, plus a forward/backward proof of each model.

Standalone (torch, numpy, huggingface_hub, mamba-ssm, momentfm); run through
scripts/gx10/gpu-run with the encoder environment. Checkpoint and architecture files are
fetched at their pinned revisions and refused unless every SHA-256 matches the config.

  embed.py wbm    --config wbm.json    --inputs inputs.npz --output wbm.npz
  embed.py moment --config moment.json --inputs inputs.npz --output moment.npz
  embed.py wbm    --config wbm.json    --prove     (synthetic forward/backward/update only)

Inputs are model-ready arrays built on the Mac (hachi.models.encoders.specs). A receipt with
shapes, finiteness, determinism, timings, peak memory and every identity goes beside the output.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import torch
from _runtime import python_headers, triton_ptxas

# Both must be set before the first Triton kernel compiles.
CPATH = python_headers()
PTXAS = triton_ptxas()

BATCH = 64
MODEL_PACKAGES = {"wbm": ("mamba-ssm", "causal-conv1d"), "moment": ("momentfm", "transformers")}


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pinned_hub_files(checkpoint):
    from huggingface_hub import hf_hub_download

    paths = {}
    for name, digest in checkpoint["files"].items():
        path = hf_hub_download(checkpoint["repository"], name, revision=checkpoint["revision"])
        if sha256(path) != digest:
            raise SystemExit(f"{checkpoint['repository']}/{name} does not match its pinned SHA-256")
        paths[name] = path
    return paths


def wbm_encoder(config, device, workdir):
    """OpenMHC's Mamba2WeekEncoder at its pinned commit, with the pinned weights loaded."""
    source = config["architecture_source"]
    package = workdir / "openmhc_wbm"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("")
    for path, digest in source["files"].items():
        url = f"https://raw.githubusercontent.com/AshleyLab/OpenMHC/{source['commit']}/{path}"
        with urlopen(Request(url, headers={"User-Agent": "hachi-gx10/1.0"}), timeout=60) as r:
            body = r.read()
        if hashlib.sha256(body).hexdigest() != digest:
            raise SystemExit(f"{path} at {source['commit']} does not match its pinned SHA-256")
        (package / Path(path).name).write_bytes(body)
    sys.path.insert(0, str(workdir))
    from openmhc_wbm.week_encoders_mamba2 import Mamba2WeekEncoder

    files = pinned_hub_files(config["checkpoint"])
    state = torch.load(files["model.ckpt"], map_location=device, weights_only=True)
    state = state.get("state_dict", state)
    weights = {}
    for key, value in state.items():
        for prefix in ("model.", "encoder."):
            if key.startswith(prefix):
                key = key.replace(prefix, "")
                break
        weights[key] = value
    arch = config["arch"]
    head = weights.get("proj_head.0.weight")
    head_type = "linear" if head is not None and head.shape[0] == arch["proj_dim"] else "mlp"
    encoder = Mamba2WeekEncoder(proj_head_type=head_type, **arch)
    result = encoder.load_state_dict(weights, strict=False)
    if result.missing_keys:
        raise SystemExit(f"WBM checkpoint is missing keys: {result.missing_keys}")
    identity = {
        "files": {name: sha256(path) for name, path in files.items()},
        "architecture_commit": source["commit"],
        "proj_head_type": head_type,
        "unexpected_keys": sorted(result.unexpected_keys),
        "parameters": sum(p.numel() for p in encoder.parameters()),
    }
    return encoder.to(device), identity


def moment_model(config, device, trainable=False):
    from momentfm import MOMENTPipeline

    checkpoint = config["checkpoint"]
    files = pinned_hub_files(checkpoint)
    kwargs = {"task_name": "embedding"}
    if trainable:
        kwargs.update(freeze_encoder=False, freeze_embedder=False)
    model = MOMENTPipeline.from_pretrained(
        checkpoint["repository"], revision=checkpoint["revision"], model_kwargs=kwargs
    )
    model.init()
    identity = {
        "files": {name: sha256(path) for name, path in files.items()},
        "parameters": sum(p.numel() for p in model.parameters()),
    }
    return model.to(device), identity


def wbm_embed(encoder, x, device):
    out = []
    with torch.no_grad():
        for start in range(0, len(x), BATCH):
            _, r = encoder(torch.from_numpy(x[start : start + BATCH]).to(device))
            out.append(r.float().cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, 256), np.float32)


def moment_embed(model, x, mask, device):
    """One univariate series per channel; a channel with no fully observed patch gives zeros."""
    n, channels, _ = x.shape
    patch = model.patch_len
    blocks, ok = [], np.zeros((n, channels), dtype=bool)
    with torch.no_grad():
        for c in range(channels):
            rows = []
            for start in range(0, n, BATCH):
                xb = torch.from_numpy(x[start : start + BATCH, c : c + 1]).to(device)
                mb = torch.from_numpy(mask[start : start + BATCH, c]).to(device)
                full = mb.unfold(-1, patch, patch).sum(-1).eq(patch).any(-1)
                emb = model.embed(x_enc=xb, input_mask=mb, reduction="mean").embeddings.float()
                emb = torch.where(full[:, None], emb, torch.zeros_like(emb))
                ok[start : start + BATCH, c] = full.cpu().numpy()
                rows.append(emb.cpu().numpy())
            blocks.append(np.concatenate(rows))
    return np.concatenate(blocks, axis=1), ok


def summary(name, array):
    norms = np.linalg.norm(array, axis=1) if len(array) else np.zeros(0)
    return {
        "name": name,
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "finite": bool(np.isfinite(array).all()),
        "row_norm_min": float(norms.min()) if len(norms) else None,
        "row_norm_mean": float(norms.mean()) if len(norms) else None,
        "row_norm_max": float(norms.max()) if len(norms) else None,
    }


def prove(model_name, model, device):
    """One synthetic forward/backward/optimizer step on unfrozen weights (never saved)."""
    torch.manual_seed(0)
    model.train()
    if model_name == "wbm":
        x = torch.randn(4, 168, 38, device=device)
        x[:, :, 19:] = (torch.rand(4, 168, 19, device=device) < 0.5).float()
    else:
        x = torch.randn(4, 1, 512, device=device)
    named = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
    params = [p for _, p in named]
    optimizer = torch.optim.SGD(params, lr=1e-3)
    before = [p.detach().clone() for p in params]
    torch.cuda.synchronize()
    began = time.perf_counter()
    if model_name == "wbm":
        _, r = model(x)
    else:
        r = model.embed(x_enc=x, input_mask=torch.ones(4, 512, device=device)).embeddings
    loss = r.float().pow(2).mean()
    loss.backward()
    # A parameter this input never reaches (e.g. a mask embedding when every step is observed)
    # has no gradient; that is reported by name, separately from non-finite gradients.
    no_grad = [n for n, p in named if p.grad is None]
    zero_grad = [n for n, p in named if p.grad is not None and not bool(p.grad.any())]
    grads_finite = all(bool(torch.isfinite(p.grad).all()) for p in params if p.grad is not None)
    optimizer.step()
    torch.cuda.synchronize()
    seconds = time.perf_counter() - began
    changed = sum(int(not torch.equal(a, p.detach())) for a, p in zip(before, params, strict=True))
    return {
        "output_shape": list(r.shape),
        "loss": float(loss.detach()),
        "loss_finite": bool(torch.isfinite(loss)),
        "trainable_tensors": len(params),
        "gradients_finite": grads_finite,
        "tensors_without_gradient": no_grad,
        "tensors_with_zero_gradient": zero_grad,
        "tensors_changed_by_update": changed,
        "forward_backward_update_ms": round(seconds * 1000, 1),
        "passed": bool(torch.isfinite(loss))
        and grads_finite
        and changed == len(params) - len(no_grad) - len(zero_grad) > 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=("wbm", "moment"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--prove", action="store_true")
    args = parser.parse_args()
    if not args.prove and not (args.inputs and args.output):
        parser.error("give --inputs and --output, or --prove")
    run_dir = Path(os.environ.get("HACHI_RUN_DIR", "."))
    device = torch.device("cuda")
    config = json.loads(args.config.read_text())
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.cuda.reset_peak_memory_stats()
    began = time.perf_counter()
    if args.model == "wbm":
        model, identity = wbm_encoder(config, device, run_dir)
    else:
        model, identity = moment_model(config, device, trainable=args.prove)
    load_seconds = time.perf_counter() - began
    receipt = {
        "model": config["model_id"],
        "checkpoint": {**config["checkpoint"], **identity},
        "config_sha256": sha256(args.config),
        "device": torch.cuda.get_device_name(0),
        "capability": list(torch.cuda.get_device_capability(0)),
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("torch", "triton", "numpy", "huggingface-hub")
            + (
                ("mamba-ssm", "causal-conv1d")
                if args.model == "wbm"
                else ("momentfm", "transformers")
            )
        },
        "host": {"machine": platform.machine(), "python": platform.python_version()},
        "load_seconds": round(load_seconds, 2),
        "triton_launcher_cpath": CPATH,
        "triton_ptxas": PTXAS,
    }
    if args.prove:
        receipt["proof"] = prove(args.model, model, device)
        output = run_dir / f"{args.model}-proof.json"
        status = receipt["proof"]["passed"]
    else:
        model.eval()
        receipt["inputs_sha256"] = sha256(args.inputs)
        arrays = {}
        with np.load(args.inputs, allow_pickle=False) as data:
            keys = {k: data[k] for k in ("subject_ids", "window_end_utc", "as_of_utc")}
            started = time.perf_counter()
            if args.model == "wbm":
                variants = sorted(k for k in data.files if k.startswith("wbm_"))
                for name in variants:
                    arrays[name] = wbm_embed(model, data[name], device)
                again = wbm_embed(model, data[variants[0]][:BATCH], device)
                receipt["determinism_max_abs_diff"] = float(
                    np.abs(again - arrays[variants[0]][:BATCH]).max()
                )
            else:
                arrays["moment"], arrays["moment_ok"] = moment_embed(
                    model, data["moment_x"], data["moment_mask"], device
                )
                again, _ = moment_embed(
                    model, data["moment_x"][:BATCH], data["moment_mask"][:BATCH], device
                )
                receipt["determinism_max_abs_diff"] = float(
                    np.abs(again - arrays["moment"][:BATCH]).max()
                )
            receipt["embed_seconds"] = round(time.perf_counter() - started, 2)
        np.savez(args.output, **keys, **arrays)
        receipt["outputs_sha256"] = sha256(args.output)
        receipt["outputs"] = [summary(k, v) for k, v in arrays.items() if v.dtype != bool]
        if "moment_ok" in arrays:
            receipt["moment_channel_ok_fraction"] = arrays["moment_ok"].mean(axis=0).tolist()
        output = args.output.with_suffix(".receipt.json")
        status = all(o["finite"] for o in receipt["outputs"])
    receipt["peak_cuda_allocated_mib"] = round(torch.cuda.max_memory_allocated() / 2**20, 1)
    receipt["peak_cuda_reserved_mib"] = round(torch.cuda.max_memory_reserved() / 2**20, 1)
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"passed": status, "receipt": str(output)}))
    return 0 if status else 1


if __name__ == "__main__":
    raise SystemExit(main())
