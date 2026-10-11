"""Derive an as-of resting signal from recorded zero-step minutes, never silent steps."""

from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from statistics import median
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from hachi.contracts.base import (
    Contract,
    IanaTimezone,
    Identifier,
    Sha256,
    SubjectId,
    UtcDatetime,
    local_day_bounds,
)
from hachi.contracts.causality import available_by
from hachi.contracts.tables import Observation
from hachi.evaluation.serialization import document_sha256

from .robust import NightlyRest

MINUTE = timedelta(minutes=1)


class NightlyRequest(Contract):
    dataset_id: Identifier
    subject_id: SubjectId
    local_date: date
    tz_name: IanaTimezone
    cutoff: UtcDatetime


class NightlyFeaturePolicy(Contract):
    """Experiment parameters; callers must freeze them before evaluation."""

    min_hr_samples_per_minute: Annotated[int, Field(gt=0)]
    min_rest_minutes: Annotated[int, Field(gt=0)]


class NightlyFeatureResult(Contract):
    request: NightlyRequest
    policy: NightlyFeaturePolicy
    night: NightlyRest
    status: Literal["observed", "night_incomplete", "insufficient_rest_minutes"]
    causal_input_sha256: Sha256
    counts: dict[str, int]


def nightly_rest(
    observations: Iterable[Observation], request: NightlyRequest, policy: NightlyFeaturePolicy
) -> NightlyFeatureResult:
    """Median of minute HR medians in complete recorded zero-step minutes.

    This path accepts point HR and complete UTC minute step totals, as exposed by
    PMData. Unsupported step spans or duplicate events are refused: upstream must
    resolve source precedence. Vendor daily RHR is not an overnight measurement.
    Recompute for each cutoff; a final snapshot summary is not a historical input.
    """
    start = local_day_bounds(request.local_date, request.tz_name)[0]
    end = datetime.combine(request.local_date, time(7), ZoneInfo(request.tz_name)).astimezone(UTC)
    counts: Counter[str] = Counter(
        dict.fromkeys(
            (
                "input_records",
                "other_metric",
                "outside_window",
                "unavailable",
                "unsupported_hr_interval",
                "accepted_hr_points",
                "accepted_step_minutes",
            ),
            0,
        )
    )
    hr: dict[datetime, list[float]] = defaultdict(list)
    steps: dict[datetime, float] = {}
    included: list[Observation] = []
    events: set[tuple[str, datetime, datetime]] = set()
    for row in observations:
        counts["input_records"] += 1
        if row.dataset_id != request.dataset_id or row.subject_id != request.subject_id:
            raise ValueError("night inputs must belong to the requested dataset and participant")
        if row.metric not in {"heart_rate", "steps"}:
            counts["other_metric"] += 1
            continue
        if not available_by(row, request.cutoff):
            counts["unavailable"] += 1
            continue
        minute = row.start_utc.replace(second=0, microsecond=0)
        if (
            row.metric == "steps"
            and row.start_utc < end
            and (row.end_utc > start or row.start_utc == row.end_utc >= start)
            and (row.start_utc != minute or row.end_utc != minute + MINUTE)
        ):
            raise ValueError("night inputs require complete aligned one-minute step totals")
        if row.start_utc < start or row.start_utc >= end or row.end_utc > end:
            counts["outside_window"] += 1
            continue
        if row.metric == "heart_rate" and row.end_utc != row.start_utc:
            counts["unsupported_hr_interval"] += 1
            continue
        event = row.metric, row.start_utc, row.end_utc
        if event in events:
            raise ValueError("duplicate native events; resolve source precedence upstream")
        events.add(event)
        included.append(row)
        if row.metric == "steps":
            steps[minute] = row.value
            counts["accepted_step_minutes"] += 1
        else:
            hr[minute].append(row.value)
            counts["accepted_hr_points"] += 1
    zero = {minute for minute, value in steps.items() if value == 0}
    matched = {minute for minute in zero if minute in hr}
    usable = {minute for minute in matched if len(hr[minute]) >= policy.min_hr_samples_per_minute}
    complete = end <= request.cutoff
    status = (
        "night_incomplete"
        if not complete
        else "insufficient_rest_minutes"
        if len(usable) < policy.min_rest_minutes
        else "observed"
    )
    value = median(median(hr[m]) for m in sorted(usable)) if status == "observed" else None
    counts.update(
        {
            "night_minutes": int((end - start) / MINUTE),
            "observed_step_minutes": len(steps),
            "unobserved_step_minutes": int((end - start) / MINUTE) - len(steps),
            "observed_zero_step_minutes": len(zero),
            "zero_step_without_hr_minutes": len(zero - matched),
            "low_hr_sample_minutes": len(matched - usable),
            "rest_minutes": len(usable),
        }
    )
    night = NightlyRest(
        subject_id=request.subject_id,
        local_date=request.local_date,
        tz_name=request.tz_name,
        start_utc=start,
        end_utc=end,
        available_at_utc=max([end, *(r.available_at_utc for r in included)]),
        rhr_bpm=value,
        # Only minutes with usable HR support the robust baseline's coverage gate.
        # The audit separately records all actually observed zero-step minutes.
        observed_zero_step_minutes=float(len(usable)),
    )
    return NightlyFeatureResult(
        request=request,
        policy=policy,
        night=night,
        status=status,
        causal_input_sha256=document_sha256(
            sorted(included, key=lambda r: (r.metric, r.start_utc, r.end_utc, r.record_id))
        ),
        counts=dict(sorted(counts.items())),
    )
