"""Runtime prerequisites shared by the GX10 encoder scripts (imported from their directory).

Triton JIT-compiles a small C launcher with gcc the first time a kernel runs, and that needs
Python.h. The GX10 interpreter has no development headers, so point CPATH at the verified
libpython3.12-dev tree that infra/gx10/encoders/build.py unpacked into the owner workspace.
"""

import os
from pathlib import Path


def python_headers() -> str | None:
    """Set CPATH to the owner's verified CPython header tree when none is configured."""
    if os.environ.get("CPATH"):
        return os.environ["CPATH"]
    root = Path(os.environ.get("HACHI_HOME", Path.home() / "hachi"))
    owner = os.environ.get("HACHI_OWNER")
    if owner is None:
        return None
    trees = sorted(
        (root / "workspaces" / owner / "toolchains").glob("python-headers-*/usr/include")
    )
    if not trees or not (trees[-1] / "python3.12/Python.h").exists():
        return None
    os.environ["CPATH"] = f"{trees[-1] / 'python3.12'}:{trees[-1]}"
    return os.environ["CPATH"]
