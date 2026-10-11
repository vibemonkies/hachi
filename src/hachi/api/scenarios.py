"""POST /v1/scenarios: sleep-schedule alertness, answered synchronously by #15's simulator.

Until `hachi.scenarios` provides `simulate(ScenarioRequest) -> AlertnessPayload`, the answer
is `unavailable`. A simulation never carries a validation or an accuracy claim.
"""

import hashlib
import importlib
import logging
from collections.abc import Callable
from pathlib import Path

from hachi.contracts.base import SCHEMA_VERSION, ArtifactRef, DataMode
from hachi.contracts.requests import ScenarioRequest
from hachi.contracts.results import (
    AlertnessPayload,
    AlertnessResult,
    ErrorResult,
    Provenance,
    ReportResult,
    UnavailableResult,
)
from hachi.evaluation.serialization import document_sha256

from .reports import now_utc
from .settings import REPOSITORY

log = logging.getLogger("hachi.api")

SIMULATOR_ARTIFACT_ID = "alertness-simulator"


def simulator() -> Callable[[ScenarioRequest], AlertnessPayload] | None:
    try:
        module = importlib.import_module("hachi.scenarios")
    except ImportError:
        return None
    simulate = getattr(module, "simulate", None)
    return simulate if callable(simulate) else None


def simulator_ref() -> ArtifactRef:
    """A simulation's artifact is its implementation: the scenario code and configuration."""
    digest = hashlib.sha256()
    module = importlib.import_module("hachi.scenarios")
    roots = [Path(module.__file__).parent, REPOSITORY / "configs" / "scenarios"]
    for root in roots:
        for path in sorted(
            p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts
        ):
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return ArtifactRef(artifact_id=SIMULATOR_ARTIFACT_ID, artifact_sha256=digest.hexdigest())


def scenario_result(request: ScenarioRequest, data_mode: DataMode, git_sha: str) -> ReportResult:
    as_of = now_utc()
    common = {
        "schema_version": SCHEMA_VERSION,
        "report_id": "scn-" + document_sha256({"request": request, "as_of": as_of})[:24],
        "subject_id": request.subject_id,
        "as_of": as_of,
        "data_mode": data_mode,
        "generated_at_utc": as_of,
        "git_sha": git_sha,
        "warnings": [],
        "replay": None,
        "task": "alertness",
    }
    simulate = simulator()
    if simulate is None:
        return ReportResult(
            UnavailableResult(
                **common,
                status="unavailable",
                reason_code="NO_ARTIFACT_FOR_TASK",
                requirements=["The #15 sleep/alertness simulator (hachi.scenarios) in this build"],
                provenance=None,
            )
        )
    try:
        payload = simulate(request)
        if not isinstance(payload, AlertnessPayload) or payload.mode != "simulation":
            raise TypeError("the scenario simulator must return a simulation AlertnessPayload")
        return ReportResult(
            AlertnessResult(
                **common,
                status="ok",
                provenance=Provenance(
                    dataset_snapshot=None, artifact=simulator_ref(), feature_coverage=[]
                ),
                alertness=payload,
            )
        )
    except (TypeError, ValueError, ArithmeticError) as exc:
        log.warning("scenario simulation failed (%s)", type(exc).__name__)
        return ReportResult(
            ErrorResult(
                **common,
                status="error",
                error_code="INFERENCE_FAILED",
                message="The sleep scenario simulation failed for these schedules.",
            )
        )
