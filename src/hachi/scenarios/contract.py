"""Translate the existing request/result contracts at the simulation boundary."""

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from hachi.contracts.requests import ScenarioRequest
from hachi.contracts.results import AlertnessResult

from .model import Curve, ModelConfig, Scenario, Schedule


def scenario_from_request(request: ScenarioRequest, config: ModelConfig) -> Scenario:
    zone = ZoneInfo(request.tz_name)
    schedules = tuple(
        Schedule(
            s.schedule_id,
            s.bedtime_local.replace(tzinfo=zone, fold=0).astimezone(UTC),
            s.wake_time_local.replace(tzinfo=zone, fold=0).astimezone(UTC),
        )
        for s in request.schedules
    )
    earliest = min(schedules, key=lambda s: (s.bedtime, s.schedule_id))
    local_date = earliest.bedtime.astimezone(zone).date()
    anchor = datetime.combine(local_date, time(config.anchor_local_hour), zone).astimezone(UTC)
    return Scenario(schedules, request.assumptions.prior_sleep_hours, anchor)


def build_result(
    request: ScenarioRequest,
    scenario: Scenario,
    config: ModelConfig,
    curves: tuple[Curve, ...],
    *,
    generated_at: datetime,
    git_sha: str,
    artifact_sha256: str,
) -> AlertnessResult:
    description = (
        f"Original conditional two-process-inspired implementation {config.version}. "
        f"UTC hours: waking S'=1-(1-S)*exp(-d/{config.tau_wake_hours}); "
        f"sleeping S'=S*exp(-d/{config.tau_sleep_hours}). "
        "Timing constants: Daan, Beersma & Borbely (1984), "
        "https://doi.org/10.1152/ajpregu.1984.246.2.R161; two-process background: "
        "https://doi.org/10.1111/jsr.12371. No population parameter fit is claimed. "
        f"B is earliest resolved bedtime; S={config.initial_pressure} at B-24h. "
        "All stated prior sleep is one synthetic block starting at B-24h, then awake to B. "
        "Each alternative stays awake from B to its own bedtime, sleeps to its wake, "
        "then stays awake through its bedtime+24 elapsed hours. Alternatives are independent. "
        f"C=cos(2*pi*(t-anchor)/24h); anchor={scenario.anchor.isoformat()}, "
        f"resolved once from {config.anchor_local_hour}:00 local on B's local date. "
        f"A=(1-S+a*(C+1))/(1+2*a), a={config.circadian_weight}. "
        "Phase, initial state, prehistory and weight are assumptions, not fitted parameters. "
        "Caffeine/light have no modeled effects; phase does not shift. "
        "A is a dimensionless illustrative index, higher=more simulated alertness; "
        "not probability, KSS, PVT, measured or causal benefit. A sleep-regulation mechanism "
        "does not validate a KSS/PVT mapping. No participant data or validation. "
        "Equation concepts are literature-derived; implementation is original, with no "
        "software code license asserted or borrowed."
    )
    return AlertnessResult.model_validate({
        "schema_version": request.schema_version,
        "report_id": "synthetic-scenario-result",
        "subject_id": request.subject_id,
        "as_of": min(s.bedtime for s in scenario.schedules),
        "generated_at_utc": generated_at,
        "git_sha": git_sha,
        "data_mode": "synthetic",
        "warnings": [], "replay": None, "status": "ok", "task": "alertness",
        "provenance": {
            "dataset_snapshot": None,
            "artifact": {"artifact_id": config.version, "artifact_sha256": artifact_sha256},
            "feature_coverage": [],
        },
        "alertness": {
            "mode": "simulation", "validation": None, "model_description": description,
            "scale": {"name": "Illustrative relative alertness", "unit": "dimensionless",
                      "minimum": 0.0, "maximum": 1.0, "higher_is_more_alert": True},
            "tz_name": request.tz_name, "assumptions": request.assumptions,
            "curves": [{"schedule_id": c.schedule_id,
                        "points": [{"time_utc": p.time_utc, "value": p.alertness}
                                   for p in c.points]} for c in curves],
        },
    })
