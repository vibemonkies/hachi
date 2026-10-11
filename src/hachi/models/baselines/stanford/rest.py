"""Rest signals on Stanford's shifted floating clock, with explicit minute-edge assumptions."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from statistics import median
from typing import Annotated, Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from hachi.contracts.base import Contract, Sha256, UtcDatetime
from hachi.evaluation.serialization import document_sha256

from ..nightly import NightlyRequest
from ..robust import NightlyRest

MINUTE = timedelta(minutes=1)


class HeartRatePoint(Contract):
    at: UtcDatetime
    bpm: Annotated[FiniteFloat, Field(ge=1, le=300)]


class StepPoint(Contract):
    at: UtcDatetime
    steps: Annotated[FiniteFloat, Field(ge=0)]

    @model_validator(mode="after")
    def _minute(self) -> Self:
        if self.at.second or self.at.microsecond:
            raise ValueError("Stanford minute step timestamps must be minute-aligned")
        return self


class StanfordRestPolicy(Contract):
    clock: Literal["floating_local_shifted"]
    step_timestamp: Literal["start", "end", "both"]
    min_hr_samples_per_minute: Annotated[int, Field(gt=0)]
    min_rest_minutes: Annotated[int, Field(gt=0)]


class StanfordRestResult(Contract):
    request: NightlyRequest
    policy: StanfordRestPolicy
    night: NightlyRest
    status: Literal["observed", "night_incomplete", "insufficient_rest_minutes"]
    causal_input_sha256: Sha256
    counts: dict[str, int]
    availability_rule: Literal["stanford-floating-sample-end-assumed-v1"] = (
        "stanford-floating-sample-end-assumed-v1"
    )


def stanford_nightly_rest(
    heart_rate: Sequence[HeartRatePoint],
    steps: Sequence[StepPoint],
    request: NightlyRequest,
    policy: StanfordRestPolicy,
) -> StanfordRestResult:
    """Caller supplies one source-reconciled participant's native points.

    There is no documented step timestamp edge or historical collection time.
    The primary 'both' policy needs explicit zero at M and M+1 to support minute
    [M,M+1) under either edge interpretation. Point HR is an explicit assumption.
    All coordinates are shifted local wall time represented with a Z suffix;
    they must never be joined with another dataset's actual UTC instants.
    """
    if (
        request.dataset_id
        not in {"stanford-covid19-wearables", "stanford-covid19-wearables-phase2"}
        or request.tz_name != "UTC"
    ):
        raise ValueError("Stanford inputs require their dataset id and floating UTC coordinates")
    start = datetime.combine(request.local_date, time(), UTC)
    end = start + timedelta(hours=7)
    counts: Counter[str] = Counter()
    hr_values: dict[datetime, set[float]] = defaultdict(set)
    step_values: dict[datetime, set[float]] = defaultdict(set)
    provenance = []
    for point in heart_rate:
        counts["hr_input_points"] += 1
        if not start <= point.at < end:
            counts["hr_outside_night"] += 1
        elif point.at > request.cutoff:
            counts["hr_unavailable"] += 1
        else:
            hr_values[point.at].add(point.bpm)
            provenance.append(("hr", point.at, point.bpm))
    first_step = start + MINUTE if policy.step_timestamp == "end" else start
    last_step = end - MINUTE if policy.step_timestamp == "start" else end
    for point in steps:
        counts["step_input_points"] += 1
        if not first_step <= point.at <= last_step:
            counts["steps_outside_night"] += 1
            continue
        ready = point.at if policy.step_timestamp == "end" else point.at + MINUTE
        if ready > request.cutoff:
            counts["steps_unavailable"] += 1
            continue
        step_values[point.at].add(point.steps)
        provenance.append(("steps", point.at, point.steps))
    # Disagreeing native values are unknown; duplicate identical values count once.
    step_map = {at: next(iter(values)) for at, values in step_values.items() if len(values) == 1}
    hr_by_minute: dict[datetime, list[float]] = defaultdict(list)
    for at, values in hr_values.items():
        if len(values) == 1:
            hr_by_minute[at.replace(second=0, microsecond=0)].append(next(iter(values)))
        else:
            counts["conflicting_hr_instants"] += 1
    counts["conflicting_step_instants"] = sum(len(v) > 1 for v in step_values.values())
    minute = start
    quiet = []
    used_ready = [end]
    while minute < end:
        at = [minute] if policy.step_timestamp == "start" else [minute + MINUTE]
        if policy.step_timestamp == "both":
            at = [minute, minute + MINUTE]
        if not all(t in step_map for t in at):
            counts["unknown_step_minutes"] += 1
        else:
            values = [step_map[t] for t in at]
            counts["observed_step_minutes"] += 1
            if all(v == 0 for v in values):
                counts["supported_zero_step_minutes"] += 1
                samples = hr_by_minute.get(minute, [])
                if len(samples) >= policy.min_hr_samples_per_minute:
                    quiet.append(median(samples))
                    used_ready.extend(
                        t if policy.step_timestamp == "end" else t + MINUTE for t in at
                    )
                else:
                    counts["zero_step_minutes_without_usable_hr"] += 1
            elif all(v > 0 for v in values):
                counts["supported_nonzero_step_minutes"] += 1
            else:
                counts["step_edge_disagreement_minutes"] += 1
        minute += MINUTE
    counts["night_minutes"] = 420
    counts["rest_minutes"] = len(quiet)
    status = (
        "night_incomplete"
        if end > request.cutoff
        else "insufficient_rest_minutes"
        if len(quiet) < policy.min_rest_minutes
        else "observed"
    )
    night = NightlyRest(
        subject_id=request.subject_id,
        local_date=request.local_date,
        tz_name="UTC",
        start_utc=start,
        end_utc=end,
        available_at_utc=max(used_ready),
        rhr_bpm=median(quiet) if status == "observed" else None,
        observed_zero_step_minutes=float(len(quiet)),
    )
    return StanfordRestResult(
        request=request,
        policy=policy,
        night=night,
        status=status,
        counts=dict(sorted(counts.items())),
        causal_input_sha256=document_sha256(
            {
                "dataset_id": request.dataset_id,
                "subject_id": request.subject_id,
                "window_start": start,
                "window_end": end,
                "policy": policy,
                "native_points": sorted(provenance),
            }
        ),
    )
