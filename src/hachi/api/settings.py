"""API configuration. Every filesystem location the API touches is decided here, by the operator.

Environment (all optional except the owner):

    HACHI_OWNER               GitHub login whose workspace and database the API uses
    HACHI_WORKSPACES          default ~/hachi/workspaces
    HACHI_DB_PATH             default <workspace>/state/metadata.sqlite3 (gpu-run sets it)
    HACHI_DATA_ROOT           approved dataset root; snapshots live in <root>/derived/<id>/
    HACHI_DATASET_SNAPSHOTS   comma-separated snapshot ids to serve, e.g. a PMData snapshot
    HACHI_ARTIFACT_ROOT       default ~/hachi/artifacts; artifacts live in <root>/<artifact_id>/
    HACHI_SERVE_ARTIFACTS     comma-separated <artifact_id>@<artifact_sha256> pins
    HACHI_SCENARIO_MODEL      two-process-v1@<sha256>: require exactly this #15 scenario bundle
    HACHI_API_PORT            default by owner (DEFAULT_PORTS)
    HACHI_API_CORS_ORIGINS    comma-separated browser origins (default: Vite on 5173)
    HACHI_GIT_SHA             default `git rev-parse HEAD` of this checkout
    HACHI_GX10_SSH            SSH destination of the GX10 (e.g. asus@5asb) for GPU models
    HACHI_GX10_CHECKOUT       GX10 clone of a merged main commit that runs inference
    HACHI_GX10_TIMEOUT        seconds one GPU job may take, queue wait included (default 180)
"""

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from hachi.contracts.base import ArtifactRef
from hachi.data.apple_health import ImportLimits
from hachi.storage import DEFAULT_ARTIFACTS, DEFAULT_WORKSPACES, Workspace, is_name

REPOSITORY = Path(__file__).resolve().parents[3]

# One API process per developer, each on its own loopback port and metadata database.
DEFAULT_PORTS = {"justin06lee": 8716, "CoffeeCoder1015": 8717, "ezzy1630": 8718}
DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    owner: str
    workspace: Workspace
    database: Path
    git_sha: str
    data_root: Path | None = None
    dataset_snapshots: tuple[str, ...] = ()
    artifact_root: Path = field(default_factory=lambda: DEFAULT_ARTIFACTS.expanduser())
    served_artifacts: tuple[ArtifactRef, ...] = ()
    # Unset: serve this checkout's scenario bundle, whose hash every result names.
    scenario_model: ArtifactRef | None = None
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    import_limits: ImportLimits = field(default_factory=ImportLimits)
    # Development and tests only: serve snapshots whose archive the registry did not admit,
    # labelled data_mode "synthetic". Never set for real data.
    allow_unadmitted_snapshots: bool = False
    # GPU models (Chronos-2) run on the GX10 through scripts/gx10/gpu-run; unset means
    # every GPU-backed forecast answers GPU_UNAVAILABLE.
    gx10_ssh: str | None = None
    gx10_checkout: str | None = None
    gx10_timeout_seconds: float = 180.0

    @property
    def port(self) -> int:
        return DEFAULT_PORTS.get(self.owner, 8716)

    @classmethod
    def from_environment(
        cls, owner: str | None = None, environ: Mapping[str, str] | None = None
    ) -> "Settings":
        env = os.environ if environ is None else environ
        owner = owner or env.get("HACHI_OWNER")
        if not owner or not is_name(owner):
            raise SettingsError("set the owner (--owner or HACHI_OWNER) to a GitHub login")
        workspaces = Path(env.get("HACHI_WORKSPACES", str(DEFAULT_WORKSPACES))).expanduser()
        workspace = Workspace.for_owner(owner, workspaces)
        database = Path(env.get("HACHI_DB_PATH", str(workspace.default_database))).expanduser()
        data_root = Path(env["HACHI_DATA_ROOT"]).expanduser() if "HACHI_DATA_ROOT" in env else None
        snapshots = _split(env.get("HACHI_DATASET_SNAPSHOTS", ""))
        if snapshots and data_root is None:
            raise SettingsError("HACHI_DATASET_SNAPSHOTS needs HACHI_DATA_ROOT")
        artifact_root = Path(env.get("HACHI_ARTIFACT_ROOT", str(DEFAULT_ARTIFACTS))).expanduser()
        return cls(
            owner=owner,
            workspace=workspace,
            database=database,
            git_sha=env.get("HACHI_GIT_SHA") or git_sha(),
            data_root=data_root,
            dataset_snapshots=snapshots,
            artifact_root=artifact_root,
            served_artifacts=tuple(
                parse_pin(p) for p in _split(env.get("HACHI_SERVE_ARTIFACTS", ""))
            ),
            scenario_model=parse_pin(env["HACHI_SCENARIO_MODEL"])
            if env.get("HACHI_SCENARIO_MODEL")
            else None,
            cors_origins=_split(env["HACHI_API_CORS_ORIGINS"])
            if "HACHI_API_CORS_ORIGINS" in env
            else DEFAULT_CORS_ORIGINS,
            gx10_ssh=env.get("HACHI_GX10_SSH") or None,
            gx10_checkout=env.get("HACHI_GX10_CHECKOUT") or None,
            gx10_timeout_seconds=float(env.get("HACHI_GX10_TIMEOUT", "180")),
        )


def _split(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def parse_pin(value: str) -> ArtifactRef:
    """`<artifact_id>@<sha256>`: the operator's pin for one served artifact."""
    artifact_id, _, digest = value.partition("@")
    try:
        return ArtifactRef(artifact_id=artifact_id, artifact_sha256=digest)
    except ValueError as exc:
        raise SettingsError(
            f"artifact pins look like <artifact_id>@<sha256>, not {value!r}"
        ) from exc


def git_sha(repository: Path = REPOSITORY) -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SettingsError("cannot read the git commit; set HACHI_GIT_SHA") from exc
    if len(sha) != 40:
        raise SettingsError("cannot read the git commit; set HACHI_GIT_SHA")
    return sha


def git_dirty(repository: Path = REPOSITORY) -> bool | None:
    try:
        output = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return bool(output.strip())
