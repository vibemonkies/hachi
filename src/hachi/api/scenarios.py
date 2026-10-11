"""POST /v1/scenarios: sleep-schedule alertness, answered synchronously.

#15's two-process simulator (`hachi.scenarios.contract.scenario_from_request` / `build_result`
around `hachi.scenarios.model.simulate`, with a frozen `two-process-v1` artifact) is not on
main yet. Until this API serves that frozen artifact, the answer is `unavailable`. Its
`as_of` follows #15's rule: the earliest bedtime, resolved in the request's timezone.
"""

from zoneinfo import ZoneInfo

from hachi.contracts.base import SCHEMA_VERSION, DataMode
from hachi.contracts.requests import ScenarioRequest, _local_to_utc
from hachi.contracts.results import ReportResult, UnavailableResult
from hachi.evaluation.serialization import document_sha256

from .reports import now_utc

REQUIREMENT = "#15's frozen two-process-v1 scenario artifact, served by this API"


def scenario_result(request: ScenarioRequest, data_mode: DataMode, git_sha: str) -> ReportResult:
    zone = ZoneInfo(request.tz_name)
    as_of = min(_local_to_utc(s.bedtime_local, zone, "bedtime") for s in request.schedules)
    return ReportResult(
        UnavailableResult(
            schema_version=SCHEMA_VERSION,
            report_id="scn-" + document_sha256(request)[:24],
            subject_id=request.subject_id,
            as_of=as_of,
            data_mode=data_mode,
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
