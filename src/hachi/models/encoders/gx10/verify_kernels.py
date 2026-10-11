"""Prove the WBM kernels on this GPU against their own PyTorch references, forward and backward.

Standalone (torch, mamba-ssm, causal-conv1d only); run through scripts/gx10/gpu-run with the
encoder environment. Inputs are seeded random tensors shaped like WBM's Mamba2 blocks; no data.
Each case compares the compiled/Triton kernel with the reference implementation shipped in the
same package and records the largest relative error of outputs and of every input gradient.
Writes kernels.json to $HACHI_RUN_DIR (or --output) and exits 1 if any case fails.
"""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import time
import traceback
from pathlib import Path

import torch

FORWARD_TOLERANCE = 2e-3
BACKWARD_TOLERANCE = 1e-2


def relative_error(actual, expected):
    scale = expected.detach().abs().max().item()
    return (actual.detach() - expected.detach()).abs().max().item() / max(scale, 1e-12)


def compare(kernel, reference, inputs, seed):
    """Run both functions on cloned leaf inputs; compare outputs and gradients."""
    k_inputs = [t.detach().clone().requires_grad_(t.requires_grad) for t in inputs]
    r_inputs = [t.detach().clone().requires_grad_(t.requires_grad) for t in inputs]
    torch.cuda.synchronize()
    began = time.perf_counter()
    k_out = kernel(*k_inputs)
    torch.cuda.synchronize()
    kernel_forward_ms = (time.perf_counter() - began) * 1000
    r_out = reference(*r_inputs)
    generator = torch.Generator(device=k_out.device).manual_seed(seed)
    upstream = torch.randn(k_out.shape, device=k_out.device, generator=generator)
    began = time.perf_counter()
    k_out.backward(upstream)
    torch.cuda.synchronize()
    kernel_backward_ms = (time.perf_counter() - began) * 1000
    r_out.backward(upstream)
    gradients = {}
    finite = bool(torch.isfinite(k_out).all())
    for index, (k, r) in enumerate(zip(k_inputs, r_inputs, strict=True)):
        if k.requires_grad:
            gradients[str(index)] = relative_error(k.grad, r.grad)
            finite = finite and bool(torch.isfinite(k.grad).all())
    forward = relative_error(k_out, r_out)
    return {
        "output_shape": list(k_out.shape),
        "forward_relative_error": forward,
        "gradient_relative_errors": gradients,
        "finite": finite,
        "kernel_forward_ms_first_call": round(kernel_forward_ms, 3),
        "kernel_backward_ms_first_call": round(kernel_backward_ms, 3),
        "passed": finite
        and forward <= FORWARD_TOLERANCE
        and all(e <= BACKWARD_TOLERANCE for e in gradients.values()),
    }


def case_causal_conv1d(device):
    from causal_conv1d import causal_conv1d_fn
    from causal_conv1d.causal_conv1d_interface import causal_conv1d_ref

    g = torch.Generator(device=device).manual_seed(1)
    x = torch.randn(2, 768, 168, device=device, generator=g, requires_grad=True)
    w = torch.randn(768, 4, device=device, generator=g, requires_grad=True)
    b = torch.randn(768, device=device, generator=g, requires_grad=True)
    return compare(
        lambda x, w, b: causal_conv1d_fn(x, w, b, activation="silu"),
        lambda x, w, b: causal_conv1d_ref(x, w, b, activation="silu"),
        [x, w, b],
        11,
    )


def case_selective_scan(device):
    from mamba_ssm.ops.selective_scan_interface import selective_scan_fn, selective_scan_ref

    g = torch.Generator(device=device).manual_seed(2)
    batch, dim, state, length = 2, 64, 16, 168
    u = torch.randn(batch, dim, length, device=device, generator=g, requires_grad=True)
    delta = (0.5 * torch.rand(batch, dim, length, device=device, generator=g)).requires_grad_()
    a = (-0.5 * torch.rand(dim, state, device=device, generator=g)).requires_grad_()
    b = torch.randn(batch, state, length, device=device, generator=g, requires_grad=True)
    c = torch.randn(batch, state, length, device=device, generator=g, requires_grad=True)
    d = torch.randn(dim, device=device, generator=g, requires_grad=True)
    return compare(
        lambda *t: selective_scan_fn(*t, delta_softplus=True),
        lambda *t: selective_scan_ref(*t, delta_softplus=True),
        [u, delta, a, b, c, d],
        12,
    )


def case_chunk_scan(device):
    from mamba_ssm.ops.triton.ssd_combined import (
        mamba_chunk_scan_combined,
        ssd_chunk_scan_combined_ref,
    )

    g = torch.Generator(device=device).manual_seed(3)
    batch, length, heads, headdim, groups, state = 2, 168, 8, 64, 1, 128
    x = torch.randn(batch, length, heads, headdim, device=device, generator=g, requires_grad=True)
    dt = (0.1 * torch.rand(batch, length, heads, device=device, generator=g)).requires_grad_()
    a = (-torch.rand(heads, device=device, generator=g)).requires_grad_()
    b = torch.randn(batch, length, groups, state, device=device, generator=g, requires_grad=True)
    c = torch.randn(batch, length, groups, state, device=device, generator=g, requires_grad=True)
    d = torch.randn(heads, device=device, generator=g, requires_grad=True)
    return compare(
        lambda *t: mamba_chunk_scan_combined(*t[:5], chunk_size=256, D=t[5]),
        lambda *t: ssd_chunk_scan_combined_ref(*t[:5], chunk_size=256, D=t[5]),
        [x, dt, a, b, c, d],
        13,
    )


def mamba2_block(device):
    from mamba_ssm import Mamba2

    torch.manual_seed(4)
    return Mamba2(d_model=256).to(device)


def case_fused_mamba2(device):
    """WBM's actual Mamba2 shape (d_model 256): the fused conv+scan+norm+out path vs its ref."""
    from einops import rearrange
    from mamba_ssm.ops.triton.ssd_combined import (
        mamba_split_conv1d_scan_combined,
        mamba_split_conv1d_scan_ref,
    )

    block = mamba2_block(device)
    g = torch.Generator(device=device).manual_seed(5)
    u = torch.randn(2, 168, 256, device=device, generator=g)
    zxbcdt = block.in_proj(u).detach().requires_grad_()
    params = [
        zxbcdt,
        rearrange(block.conv1d.weight, "d 1 w -> d w").detach().requires_grad_(),
        block.conv1d.bias.detach().requires_grad_(),
        block.dt_bias.detach().requires_grad_(),
        (-torch.exp(block.A_log.float())).detach().requires_grad_(),
        block.D.detach().requires_grad_(),
        block.norm.weight.detach().requires_grad_(),
        block.out_proj.weight.detach().requires_grad_(),
    ]

    def call(fn):
        def run(z, w, b, dt_bias, a, d, norm, out):
            return fn(
                z,
                w,
                b,
                dt_bias,
                a,
                d,
                block.chunk_size,
                activation=block.activation,
                rmsnorm_weight=norm,
                rmsnorm_eps=block.norm.eps,
                outproj_weight=out,
                outproj_bias=None,
                headdim=block.headdim,
                ngroups=block.ngroups,
                norm_before_gate=block.norm_before_gate,
            )

        return run

    return compare(
        call(mamba_split_conv1d_scan_combined), call(mamba_split_conv1d_scan_ref), params, 14
    )


def case_module_paths(device):
    """The module's two kernel paths (fused, and unfused conv + chunk scan) must agree."""
    block = mamba2_block(device)
    g = torch.Generator(device=device).manual_seed(6)
    u = torch.randn(2, 168, 256, device=device, generator=g, requires_grad=True)

    def path(fused):
        def run(u):
            block.use_mem_eff_path = fused
            return block(u)

        return run

    return compare(path(True), path(False), [u], 15)


def library_files():
    out = {}
    for module in ("selective_scan_cuda", "causal_conv1d_cuda"):
        spec = importlib.util.find_spec(module)
        if spec and spec.origin:
            path = Path(spec.origin)
            out[module] = {
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or Path(os.environ["HACHI_RUN_DIR"]) / "kernels.json"
    device = torch.device("cuda")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    report = {
        "host": {"machine": platform.machine(), "python": platform.python_version()},
        "device": torch.cuda.get_device_name(0),
        "capability": list(torch.cuda.get_device_capability(0)),
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("torch", "triton", "mamba-ssm", "causal-conv1d", "einops")
        },
        "torch_cuda": torch.version.cuda,
        "triton_ptxas_path": os.environ.get("TRITON_PTXAS_PATH"),
        "tolerances": {"forward": FORWARD_TOLERANCE, "backward": BACKWARD_TOLERANCE},
        "cases": {},
    }
    try:
        report["extensions"] = library_files()
    except Exception as error:  # an import failure is itself the evidence
        report["extensions"] = {"error": f"{type(error).__name__}: {error}"}
    torch.cuda.reset_peak_memory_stats()
    for name, case in (
        ("causal_conv1d_cuda", case_causal_conv1d),
        ("selective_scan_cuda", case_selective_scan),
        ("ssd_chunk_scan_triton", case_chunk_scan),
        ("mamba2_fused_conv_scan_norm_triton", case_fused_mamba2),
        ("mamba2_module_fused_vs_unfused", case_module_paths),
    ):
        try:
            report["cases"][name] = case(device)
        except Exception as error:
            report["cases"][name] = {
                "passed": False,
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(limit=8),
            }
        print(name, json.dumps(report["cases"][name])[:400], flush=True)
    report["peak_cuda_allocated_mib"] = round(torch.cuda.max_memory_allocated() / 2**20, 1)
    report["passed"] = all(c.get("passed") for c in report["cases"].values())
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "output": str(output)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
