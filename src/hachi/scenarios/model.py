"""Original, deterministic implementation of disclosed two-process-inspired equations."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import cos, exp, isfinite, pi


@dataclass(frozen=True)
class ModelConfig:
    version: str
    tau_wake_hours: float
    tau_sleep_hours: float
    initial_pressure: float
    circadian_weight: float
    anchor_local_hour: int
    sample_minutes: int

    def __post_init__(self) -> None:
        for value in (self.tau_wake_hours, self.tau_sleep_hours):
            if not isfinite(value) or value <= 0:
                raise ValueError("time constants must be finite and positive")
        if not isfinite(self.initial_pressure) or not 0 <= self.initial_pressure <= 1:
            raise ValueError("initial pressure must lie in [0,1]")
        if not isfinite(self.circadian_weight) or self.circadian_weight < 0:
            raise ValueError("circadian weight must be finite and nonnegative")
        if type(self.anchor_local_hour) is not int or not 0 <= self.anchor_local_hour <= 23:
            raise ValueError("anchor_local_hour must be an integer in [0,23]")
        if type(self.sample_minutes) is not int or self.sample_minutes != 30:
            raise ValueError("this model samples every 30 minutes")
        if self.version != "two-process-v1":
            raise ValueError("unsupported model version")


@dataclass(frozen=True)
class Schedule:
    schedule_id: str
    bedtime: datetime
    wake: datetime

    def __post_init__(self) -> None:
        for instant in (self.bedtime, self.wake):
            if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
                raise ValueError("schedule instants must be UTC")
        if not timedelta(0) < self.wake - self.bedtime <= timedelta(hours=16):
            raise ValueError("elapsed sleep must be in (0,16] hours")


@dataclass(frozen=True)
class Scenario:
    schedules: tuple[Schedule, ...]
    prior_sleep_hours: float
    anchor: datetime

    def __post_init__(self) -> None:
        if not 1 <= len(self.schedules) <= 4:
            raise ValueError("one to four alternative schedules are required")
        if len({s.schedule_id for s in self.schedules}) != len(self.schedules):
            raise ValueError("schedule ids must be unique")
        if not isfinite(self.prior_sleep_hours) or not 0 <= self.prior_sleep_hours <= 24:
            raise ValueError("prior sleep must lie in [0,24] hours")
        if self.anchor.tzinfo is None or self.anchor.utcoffset() != timedelta(0):
            raise ValueError("anchor must be UTC")


@dataclass(frozen=True)
class Point:
    time_utc: datetime
    pressure: float
    circadian: float
    alertness: float


@dataclass(frozen=True)
class Curve:
    schedule_id: str
    points: tuple[Point, ...]


def simulate(scenario: Scenario, config: ModelConfig) -> tuple[Curve, ...]:
    """Each alternative shares prehistory; returned curves contain waking instants only."""
    earliest = min(s.bedtime for s in scenario.schedules)
    prior = scenario.prior_sleep_hours
    pressure = config.initial_pressure * exp(-prior / config.tau_sleep_hours)
    pressure = 1 - (1 - pressure) * exp(-(24 - prior) / config.tau_wake_hours)
    curves = []
    for schedule in sorted(scenario.schedules, key=lambda s: (s.bedtime, s.schedule_id)):
        delay = (schedule.bedtime - earliest).total_seconds() / 3600
        bedtime_pressure = 1 - (1 - pressure) * exp(-delay / config.tau_wake_hours)
        sleep = (schedule.wake - schedule.bedtime).total_seconds() / 3600
        wake_pressure = bedtime_pressure * exp(-sleep / config.tau_sleep_hours)
        end = schedule.bedtime + timedelta(hours=24)
        instant = schedule.wake
        points = []
        while True:
            awake = (instant - schedule.wake).total_seconds() / 3600
            s = 1 - (1 - wake_pressure) * exp(-awake / config.tau_wake_hours)
            phase = (instant - scenario.anchor).total_seconds() / 3600
            c = cos(2 * pi * phase / 24)
            a = (1 - s + config.circadian_weight * (c + 1)) / (1 + 2 * config.circadian_weight)
            points.append(Point(instant.astimezone(UTC), s, c, a))
            if instant == end:
                break
            instant = min(instant + timedelta(minutes=config.sample_minutes), end)
        curves.append(Curve(schedule.schedule_id, tuple(points)))
    return tuple(curves)
