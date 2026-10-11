"""Synthetic GPU math and a pinned pretrained Chronos-2 inference/training step."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

import torch
from chronos import Chronos2Pipeline
from huggingface_hub import snapshot_download


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    started = time.monotonic()
    source = Path(__file__).resolve().parents[2]
    run = Path(os.environ["HACHI_RUN_DIR"])
    specification = json.loads((source / "infra/gx10/model.json").read_text())
    assert torch.cuda.is_available(), "CUDA is unavailable"
    assert platform.machine() == "aarch64"
    assert torch.cuda.get_device_capability(0) == (12, 1), "expected GB10 sm_121"
    torch.set_num_threads(4)
    torch.manual_seed(42)
    torch.cuda.reset_peak_memory_stats()

    a = torch.randn(512, 512, device="cuda")
    b = torch.randn(512, 512, device="cuda")
    math_start = time.monotonic()
    result = a @ b
    torch.cuda.synchronize()
    math_seconds = time.monotonic() - math_start
    torch.testing.assert_close(result.cpu(), a.cpu() @ b.cpu(), rtol=1e-4, atol=1e-3)
    del a, b, result

    download_start = time.monotonic()
    snapshot = Path(snapshot_download(specification["model_id"], revision=specification["revision"],
                                     allow_patterns=["config.json", "model.safetensors"]))
    download_seconds = time.monotonic() - download_start
    weights_hash = sha256(snapshot / "model.safetensors")
    assert weights_hash == specification["weights_sha256"], "checkpoint checksum failed"
    pipeline = Chronos2Pipeline.from_pretrained(str(snapshot), device_map="cuda", torch_dtype=torch.float32)
    model = pipeline.model
    assert all(parameter.device.type == "cuda" for parameter in model.parameters())
    context = torch.sin(torch.arange(128, device="cuda", dtype=torch.float32) / 8)[None, :]
    target = torch.sin(torch.arange(128, 144, device="cuda", dtype=torch.float32) / 8)[None, :]
    # The public pipeline pins CPU inputs, then transfers batches to its CUDA model.
    inference_context = context.cpu()

    model.eval()
    with torch.no_grad():
        # Warm up kernels before timing the public inference path.
        pipeline.predict([inference_context], prediction_length=16)
        torch.cuda.synchronize()
        inference_start = time.monotonic()
        prediction = pipeline.predict([inference_context], prediction_length=16)
        torch.cuda.synchronize()
        inference_seconds = time.monotonic() - inference_start
    assert len(prediction) == 1
    assert prediction[0].shape[-1] == 16
    assert torch.isfinite(prediction[0]).all()

    model.train()
    optimizer = torch.optim.SGD(model.parameters(), lr=1e-4)
    before = model.output_patch_embedding.output_layer.weight.detach().clone()
    step_start = time.monotonic()
    output = model(context=context, future_target=target, num_output_patches=1)
    assert output.loss is not None and torch.isfinite(output.loss)
    output.loss.backward()
    gradients = [parameter.grad for parameter in model.parameters() if parameter.grad is not None]
    assert gradients and all(torch.isfinite(gradient).all() for gradient in gradients)
    assert any(torch.count_nonzero(gradient).item() for gradient in gradients)
    optimizer.step()
    torch.cuda.synchronize()
    step_seconds = time.monotonic() - step_start
    assert not torch.equal(before, model.output_patch_embedding.output_layer.weight), "optimizer made no update"

    evidence = {
        "status": "passed", "data": "synthetic sine wave; no participant data",
        "owner": os.environ["HACHI_OWNER"], "python": sys.version,
        "python_executable": sys.executable, "architecture": platform.machine(),
        "torch": torch.__version__, "torch_cuda": torch.version.cuda,
        "compiled_cuda_arches": torch.cuda.get_arch_list(),
        "gpu": torch.cuda.get_device_name(0), "capability": list(torch.cuda.get_device_capability(0)),
        "gpu_identity": subprocess.check_output(["nvidia-smi", "--query-gpu=uuid,name,driver_version",
                                                "--format=csv,noheader"], text=True).strip(),
        "packages": {name: importlib.metadata.version(name) for name in
                     ("chronos-forecasting", "transformers", "accelerate", "numpy", "pandas")},
        "source_base_commit": subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                                      text=True).strip(),
        "source_sha256": {str(path.relative_to(source)): sha256(path) for path in
                          [Path(__file__).resolve(), source / "infra/gx10/model.json",
                           source / "scripts/gx10/gpu-run", source / "scripts/gx10/supervise.py"]},
        "lock_sha256": sha256(source / "infra/gx10/requirements.lock"),
        "model": specification, "weights_sha256": weights_hash,
        "tensor_matmul_seconds": math_seconds, "download_seconds": download_seconds,
        "inference_seconds": inference_seconds, "forward_backward_update_seconds": step_seconds,
        "loss": output.loss.item(), "prediction_shape": list(prediction[0].shape),
        "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
        "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved(),
        "peak_process_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "total_seconds": time.monotonic() - started,
        "wbm_mamba": "not attempted; separate admission gate remains open",
    }
    (run / "runtime.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
