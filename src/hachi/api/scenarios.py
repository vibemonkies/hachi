"""POST /v1/scenarios: sleep-schedule alertness, simulated synchronously by #15's model.

The answer is #15's conditional `two-process-v1` simulation (`hachi.scenarios`): the request
becomes a scenario (`scenario_from_request`), `simulate` gives one curve per schedule, and
`build_result` returns an AlertnessResult with mode `simulation`, no validation, data_mode
`synthetic`, no dataset snapshot and the request's assumptions echoed. Nothing about the
subject is read or stored. Its `as_of` is the earliest bedtime, resolved in the request's
timezone.

The model's identity is the bundle `hachi.scenarios.demo` archives (the configuration plus
the implementation sources and README), hashed exactly as the demo hashes it. An operator can
pin it (HACHI_SCENARIO_MODEL=two-process-v1@<sha256>); a checkout whose bundle differs then
answers unavailable rather than simulating with other code.
"""

import json
import tomllib
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import hachi.scenarios
from hachi.contracts.base import SCHEMA_VERSION, ArtifactRef
from hachi.contracts.requests import ScenarioRequest, _local_to_utc
from hachi.contracts.results import ReportResult, UnavailableResult
from hachi.evaluation.serialization import document_sha256
from hachi.scenarios.contract import build_result, scenario_from_request
from hachi.scenarios.model import ModelConfig, simulate

from .errors import ApiProblem
from .reports import now_utc

CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "scenarios" / "two-process-v1.toml"
# Exactly the files hachi.scenarios.demo archives in model-artifact.json, in its order.
SOURCE_FILES = ("__init__.py", "model.py", "contract.py", "demo.py", "README.md")
REQUIREMENT = "#15's two-process-v1 scenario model, matching this API's pinned bundle"


@dataclass(frozen=True)
class ScenarioModel:
    config: ModelConfig
    ref: ArtifactRef


def load_scenario_model(pin: ArtifactRef | None = None) -> ScenarioModel:
    """This checkout's two-process-v1 bundle; refused if it differs from the operator's pin."""
    model_bytes = CONFIG_PATH.read_bytes()
    config = ModelConfig(**tomllib.loads(model_bytes.decode("utf-8")))
    source = Path(hachi.scenarios.__file__).parent
    bundle = {"model.toml": model_bytes.decode("utf-8")}
    for name in SOURCE_FILES:
        bundle[name] = (source / name).read_text(encoding="utf-8")
    digest = sha256(json.dumps(bundle, sort_keys=True, ensure_ascii=True).encode("utf-8"))
    ref = ArtifactRef(artifact_id=config.version, artifact_sha256=digest.hexdigest())
    if pin is not None and pin != ref:
        raise ValueError("the scenario model's bundle differs from its pin")
    return ScenarioModel(config, ref)


def scenario_result(
    request: ScenarioRequest, model: ScenarioModel | None, git_sha: str
) -> ReportResult:
    report_id = "scn-" + document_sha256(request)[:24]
    if model is None:
        zone = ZoneInfo(request.tz_name)
        return ReportResult(
            UnavailableResult(
                schema_version=SCHEMA_VERSION,
                report_id=report_id,
                subject_id=request.subject_id,
                as_of=min(
                    _local_to_utc(s.bedtime_local, zone, "bedtime") for s in request.schedules
                ),
                data_mode="synthetic",
                generated_at_utc=now_utc(),
                git_sha=git_sha,
                warnings=[],
                replay=None,
                status="unavailable",
                task="alertness",
                reason_code="NO_ARTIFACT_FOR_TASK",
                requirements=[REQUIREMENT],
                provenance=None,
            )
        )
    try:
        scenario = scenario_from_request(request, model.config)
        curves = simulate(scenario, model.config)
    except (ValueError, OverflowError) as exc:  # the domain's limits; the contract checks most
        raise ApiProblem(
            "VALIDATION_FAILED", "The schedules are outside what the scenario model accepts."
        ) from exc
    result = build_result(
        request,
        scenario,
        model.config,
        curves,
        generated_at=now_utc(),
        git_sha=git_sha,
        artifact_sha256=model.ref.artifact_sha256,
    )
    return ReportResult(result.model_copy(update={"report_id": report_id}))
