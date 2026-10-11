"""Cutoff-aware nightly deviation comparator, distinct from upstream NightSignal."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from statistics import median
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from hachi.contracts.base import (
    Contract,
    IanaTimezone,
    SubjectId,
    UtcDatetime,
    local_day_bounds,
    require_ordered,
)
from hachi.contracts.requests import ConfounderEntry


class NightlyRest(Contract):
    """An ingestion-derived summary; missing steps must produce an unavailable RHR.

    The caller supplies source-audited local-night intervals and actual zero-step
    coverage. Vendor daily RHR and silent step periods are incompatible substitutes.
    """

    subject_id: SubjectId
    local_date: date
    tz_name: IanaTimezone
    start_utc: UtcDatetime
    end_utc: UtcDatetime
    available_at_utc: UtcDatetime
    rhr_bpm: Annotated[float, Field(ge=1, le=300)] | None
    observed_zero_step_minutes: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def _interval(self) -> Self:
        require_ordered(self.start_utc, self.end_utc, "night", allow_equal=False)
        expected_start = local_day_bounds(self.local_date, self.tz_name)[0]
        expected_end = datetime.combine(
            self.local_date, time(7), ZoneInfo(self.tz_name)
        ).astimezone(UTC)
        if self.start_utc != expected_start or self.end_utc != expected_end:
            raise ValueError("night must identify the complete local midnight-to-07:00 window")
        if self.available_at_utc < self.end_utc:
            raise ValueError("nightly summary cannot be available before it is complete")
        if self.observed_zero_step_minutes > (self.end_utc - self.start_utc).total_seconds() / 60:
            raise ValueError("observed quiet minutes cannot exceed the night interval")
        return self


class RobustConfig(Contract):
    baseline_days: Annotated[int, Field(gt=0)] = 28
    min_nights: Annotated[int, Field(ge=2)] = 7
    min_zero_step_minutes: Annotated[float, Field(gt=0)] = 30.0
    scale_floor_bpm: Annotated[float, Field(gt=0)] = 1.0
    alert_threshold: Annotated[float, Field(gt=0)] = 3.0
    direction: Literal["up", "two_sided"] = "two_sided"


class DeviationScore(Contract):
    kind: Literal["scored"] = "scored"
    model_id: Literal["causal-nightly-mad-v1"] = "causal-nightly-mad-v1"
    baseline_median_bpm: float
    scale_bpm: float
    robust_z: float
    score: float
    alert: bool
    baseline_nights: int
    excluded_missing_nights: int
    excluded_confounder_nights: int
    known_confounders: tuple[str, ...]


class DeviationAbstention(Contract):
    kind: Literal["abstained"] = "abstained"
    model_id: Literal["causal-nightly-mad-v1"] = "causal-nightly-mad-v1"
    reason: Literal["night_unavailable", "missing_rest_measurement", "cold_start"]
    baseline_nights: int
    excluded_missing_nights: int
    excluded_confounder_nights: int
    known_confounders: tuple[str, ...]


type DeviationResult = DeviationScore | DeviationAbstention


def nightly_deviation(
    night: NightlyRest,
    history: Sequence[NightlyRest],
    config: RobustConfig,
    *,
    cutoff: UtcDatetime,
    confounders: Sequence[ConfounderEntry] = (),
) -> DeviationResult:
    """No interpolation, current-night baseline update, or illness probability.

    The configured threshold/floor are experiment parameters. They are not a
    calibrated alert policy until frozen and evaluated on the real validation set.
    """
    if any(n.subject_id != night.subject_id for n in history):
        raise ValueError("night history must contain only the requested participant")
    if any(n.tz_name != night.tz_name for n in history):
        raise ValueError("night history requires a consistent declared timezone")
    intervals = sorted(history, key=lambda n: n.start_utc)
    if cutoff.utcoffset() != timedelta(0):
        raise ValueError("cutoff requires a UTC-aware instant")
    if any(b.start_utc < a.end_utc for a, b in pairwise(intervals)):
        raise ValueError("night history must be deduplicated and non-overlapping")

    def factors(n: NightlyRest) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    c.factor
                    for c in confounders
                    if c.entered_at_utc <= cutoff
                    and c.occurred_earliest_utc < n.end_utc
                    and c.occurred_latest_utc >= n.start_utc
                }
            )
        )

    known = factors(night)
    if night.end_utc > cutoff or night.available_at_utc > cutoff:
        return DeviationAbstention(
            reason="night_unavailable",
            baseline_nights=0,
            excluded_missing_nights=0,
            excluded_confounder_nights=0,
            known_confounders=known,
        )
    if night.rhr_bpm is None or night.observed_zero_step_minutes < config.min_zero_step_minutes:
        return DeviationAbstention(
            reason="missing_rest_measurement",
            baseline_nights=0,
            excluded_missing_nights=0,
            excluded_confounder_nights=0,
            known_confounders=known,
        )
    start = night.local_date - timedelta(days=config.baseline_days)
    prior = [
        n
        for n in intervals
        if n.local_date >= start and n.end_utc <= night.start_utc and n.available_at_utc <= cutoff
    ]
    values: list[float] = []
    missing = confounded = 0
    for n in prior:
        if n.rhr_bpm is None or n.observed_zero_step_minutes < config.min_zero_step_minutes:
            missing += 1
        elif factors(n):
            confounded += 1
        else:
            values.append(n.rhr_bpm)
    counts = {
        "baseline_nights": len(values),
        "excluded_missing_nights": missing,
        "excluded_confounder_nights": confounded,
        "known_confounders": known,
    }
    if len(values) < config.min_nights:
        return DeviationAbstention(reason="cold_start", **counts)
    center = median(values)
    # Normal-consistent MAD with an explicit floor for flat/quantized baselines.
    scale = max(config.scale_floor_bpm, 1.4826 * median(abs(v - center) for v in values))
    z = (night.rhr_bpm - center) / scale
    score = max(0.0, z) if config.direction == "up" else abs(z)
    return DeviationScore(
        baseline_median_bpm=center,
        scale_bpm=scale,
        robust_z=z,
        score=score,
        alert=score >= config.alert_threshold,
        **counts,
    )
