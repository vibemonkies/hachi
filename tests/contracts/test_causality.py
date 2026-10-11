"""Sentinel tests for the cutoff rule every feature pipeline and evaluator shares."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hachi.contracts import (
    Observation,
    Outcome,
    available_by,
    label_known_by,
    observations_available_by,
)

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
CUTOFF = datetime(2026, 10, 10, 7, tzinfo=UTC)


def obs(start: datetime, end: datetime, available: datetime, value: float = 60.0) -> Observation:
    raw = json.loads((FIXTURES / "Observation" / "heart-rate-sample.json").read_text())
    raw["record_id"] = f"r{int(start.timestamp())}-{int(available.timestamp())}"
    raw.update(start_utc=start, end_utc=end, available_at_utc=available, value=value)
    return Observation.model_validate(raw)


def test_backdated_record_is_excluded() -> None:
    before = CUTOFF - timedelta(hours=3)
    backdated = obs(before, before, CUTOFF + timedelta(minutes=1))
    assert not available_by(backdated, CUTOFF)


def test_record_available_exactly_at_cutoff_is_included() -> None:
    assert available_by(obs(CUTOFF - timedelta(hours=1), CUTOFF, CUTOFF), CUTOFF)


def test_interval_spanning_the_cutoff_is_excluded() -> None:
    spanning = obs(CUTOFF - timedelta(hours=1), CUTOFF + timedelta(hours=1), CUTOFF)
    assert not available_by(spanning, CUTOFF)


def test_changing_withheld_values_cannot_change_what_is_visible() -> None:
    times = [CUTOFF + timedelta(hours=h) for h in range(-48, 48, 6)]
    history = [obs(t, t, t + timedelta(minutes=5), value=60.0) for t in times]
    altered = [
        o if available_by(o, CUTOFF) else o.model_copy(update={"value": 180.0}) for o in history
    ]
    assert observations_available_by(history, CUTOFF) == observations_available_by(altered, CUTOFF)


def test_labels_are_known_only_once_recorded() -> None:
    def outcome(name: str) -> Outcome:
        return Outcome.model_validate_json((FIXTURES / "Outcome" / f"{name}.json").read_text())

    episode = outcome("symptom-episode-censored").root
    assert label_known_by(episode, episode.observed_at_utc)
    assert not label_known_by(episode, episode.observed_at_utc - timedelta(seconds=1))
    unknown = outcome("status-unknown-no-survey").root
    assert not label_known_by(unknown, unknown.end_utc + timedelta(days=365))


def test_cutoff_must_be_utc() -> None:
    record = obs(CUTOFF - timedelta(hours=1), CUTOFF - timedelta(hours=1), CUTOFF)
    with pytest.raises(ValueError, match="UTC"):
        available_by(record, CUTOFF.replace(tzinfo=None))
