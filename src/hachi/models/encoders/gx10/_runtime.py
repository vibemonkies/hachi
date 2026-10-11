"""Runtime prerequisites shared by the GX10 encoder scripts (imported from their directory).

Triton JIT-compiles a small C launcher with gcc the first time a kernel runs, and that needs
Python.h. The GX10 interpreter has no development headers, so point CPATH at the verified
libpython3.12-dev tree that infra/gx10/encoders/build.py unpacked into the owner workspace.

Triton 3.4 bundles ptxas from CUDA 12.8, which rejects GB10's ``sm_121a``. The verified CUDA
12.9.1 toolchain from the same build step knows it, so TRITON_PTXAS_PATH points there.
"""

import os
from pathlib import Path


def _toolchains() -> Path | None:
    owner = os.environ.get("HACHI_OWNER")
    if owner is None:
        return None
    return (
        Path(os.environ.get("HACHI_HOME", Path.home() / "hachi"))
        / "workspaces"
        / owner
        / "toolchains"
    )


def triton_ptxas() -> str | None:
    """Set TRITON_PTXAS_PATH to the owner's CUDA 12.9 ptxas when none is configured."""
    if os.environ.get("TRITON_PTXAS_PATH"):
        return os.environ["TRITON_PTXAS_PATH"]
    root = _toolchains()
    found = sorted(root.glob("cuda-12.9*/bin/ptxas")) if root else []
    if not found:
        return None
    os.environ["TRITON_PTXAS_PATH"] = str(found[-1])
    return os.environ["TRITON_PTXAS_PATH"]


def python_headers() -> str | None:
    """Set CPATH to the owner's verified CPython header tree when none is configured."""
    if os.environ.get("CPATH"):
        return os.environ["CPATH"]
    root = _toolchains()
    trees = sorted(root.glob("python-headers-*/usr/include")) if root else []
    if not trees or not (trees[-1] / "python3.12/Python.h").exists():
        return None
    os.environ["CPATH"] = f"{trees[-1] / 'python3.12'}:{trees[-1]}"
    return os.environ["CPATH"]
