"""Record whether a compiled causal-conv1d build actually runs a kernel on this GPU.

Standalone; run through scripts/gx10/gpu-run in a disposable environment holding the wheel
under test. Used to keep the upstream build's failure on GB10 (sm_121) as evidence: its
setup.py only emits gencodes up to sm_90 without PTX, so importing works but launching fails.
Writes kernel-image-probe.json to $HACHI_RUN_DIR.
"""

import importlib.metadata
import json
import os
import traceback
from pathlib import Path

import torch


def main() -> int:
    report = {
        "device": torch.cuda.get_device_name(0),
        "capability": list(torch.cuda.get_device_capability(0)),
        "torch": torch.__version__,
        "causal_conv1d": importlib.metadata.version("causal-conv1d"),
    }
    try:
        import causal_conv1d_cuda  # noqa: F401
        from causal_conv1d import causal_conv1d_fn

        report["import"] = "ok"
        x = torch.randn(1, 64, 168, device="cuda")
        weight = torch.randn(64, 4, device="cuda")
        out = causal_conv1d_fn(x, weight, None, activation="silu")
        torch.cuda.synchronize()
        report["kernel"] = {"ran": True, "finite": bool(torch.isfinite(out).all())}
    except Exception as error:
        report["kernel"] = {
            "ran": False,
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc(limit=6),
        }
    path = Path(os.environ.get("HACHI_RUN_DIR", ".")) / "kernel-image-probe.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["kernel"])[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
