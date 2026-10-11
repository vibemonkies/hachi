"""What may inform a prediction made at a cutoff.

A record informs a prediction at `cutoff` only if it had ended and had become available by
then. A backdated entry (ended before the cutoff, created after it) is excluded.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta

from .tables import Observation, StatusUnknown, SymptomEpisode, TestResult


def _require_utc(cutoff: datetime) -> None:
    if cutoff.utcoffset() != timedelta(0):
        raise ValueError("cutoff must be a UTC-aware datetime")


def available_by(observation: Observation, cutoff: datetime) -> bool:
    _require_utc(cutoff)
    return observation.end_utc <= cutoff and observation.available_at_utc <= cutoff


def observations_available_by(
    observations: Iterable[Observation], cutoff: datetime
) -> list[Observation]:
    return [o for o in observations if available_by(o, cutoff)]


def label_known_by(outcome: SymptomEpisode | TestResult | StatusUnknown, cutoff: datetime) -> bool:
    """Whether an outcome label had been recorded by the cutoff. Unknown status is never a label."""
    _require_utc(cutoff)
    return not isinstance(outcome, StatusUnknown) and outcome.observed_at_utc <= cutoff
