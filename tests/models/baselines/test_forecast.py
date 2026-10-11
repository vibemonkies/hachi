from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from hachi.contracts.manifests import TimeWindow
from hachi.contracts.tables import Observation
from hachi.evaluation import ForecastEstimate, ForecastInput, TrainingPrefix
from hachi.models.baselines import BaselineArtifact, BaselineConfig, fit_baseline, hourly_values

BASE = datetime(2026, 10, 10, tzinfo=UTC)
HOUR = timedelta(hours=1)


def row(subject: str, hour: int, value: float, *, delay: int = 0) -> Observation:
    start = BASE + hour * HOUR
    return Observation(
        dataset_id="synthetic",
        subject_id=subject,
        record_id=f"{subject}-{hour}-{value}-{delay}".replace(".", "_"),
        source_kind="research_device",
        source_id="generated",
        device_model=None,
        metric="heart_rate",
        unit="bpm",
        value=value,
        start_utc=start,
        end_utc=start + timedelta(minutes=15),
        available_at_utc=start + timedelta(minutes=15) + delay * HOUR,
        availability="observed",
        availability_rule=None,
        tz_name="UTC",
        utc_offset_minutes=0,
        tz_provenance="dataset_documentation",
    )


def request(history=(), *, cutoff=BASE, horizon=2) -> ForecastInput:
    return ForecastInput(
        "held-out",
        cutoff,
        tuple(
            TimeWindow(start_utc=cutoff + h * HOUR, end_utc=cutoff + (h + 1) * HOUR)
            for h in range(horizon)
        ),
        tuple(history),
    )


def artifact(method, observations=(), **kwargs) -> BaselineArtifact:
    return fit_baseline(
        TrainingPrefix(BASE, ("train-a", "train-b"), tuple(observations)),
        BaselineConfig(method=method, metric="heart_rate", aggregation="mean", **kwargs),
    )


def test_last_complete_hour_uses_declared_aggregation_and_abstains_when_stale():
    fitted = artifact("last_valid", max_age_hours=2)
    history = [row("held-out", -1, 60.0), row("held-out", -1, 80.0)]
    assert fitted.predict(request(history)) == (ForecastEstimate(median=70.0),) * 2
    assert fitted.predict(request([row("held-out", -3, 90.0)])) == (None, None)
    assert fitted.predict(request()) == (None, None)


def test_future_backdated_and_incomplete_hours_cannot_change_prediction():
    fitted = artifact("last_valid")
    known = row("held-out", -1, 60.0)
    late = row("held-out", -1, 200.0, delay=2)
    future = row("held-out", 0, 250.0)
    assert fitted.predict(request([known, late, future])) == fitted.predict(request([known]))
    earlier = BASE - timedelta(minutes=30)
    assert hourly_values([known], fitted.config, earlier) == ()


def test_spanning_interval_is_omitted_and_samples_do_not_claim_coverage():
    fitted = artifact("last_valid", min_samples_per_hour=2)
    known = row("held-out", -1, 60.0)
    spanning = Observation.model_validate(
        {**row("held-out", -2, 200.0).model_dump(), "end_utc": BASE}
    )
    assert fitted.predict(request([known, spanning])) == (None, None)
    values = hourly_values([known, row("held-out", -1, 80.0)], fitted.config, BASE)
    assert values[0].samples == 2 and values[0].value == 70.0


def test_utc_seasonal_bins_do_not_use_future_or_fill_missing_phase():
    fitted = artifact("seasonal_naive")
    history = [row("held-out", -24, 70.0), row("held-out", -23, 80.0)]
    assert fitted.predict(request(history)) == (
        ForecastEstimate(median=70.0),
        ForecastEstimate(median=80.0),
    )
    assert fitted.predict(request(history[:1])) == (ForecastEstimate(median=70.0), None)
    assert fitted.predict(request(history, horizon=26))[24:] == fitted.predict(request(history))
    delayed = row("held-out", -23, 80.0, delay=24)
    assert fitted.predict(request([history[0], delayed]))[-1] is None


def test_population_mean_weights_participants_equally_and_stays_frozen():
    training = [row("train-a", h, 60.0) for h in range(-10, 0)]
    training += [row("train-b", -1, 100.0)]
    training += [row("train-b", -1, 250.0, delay=2)]
    fitted = artifact("train_population_mean", training)
    assert fitted.population_mean == 80.0
    assert fitted.training_participants == 2 and fitted.training_hours == 11
    assert (
        fitted.predict(request([row("held-out", -1, 250.0)]))
        == (ForecastEstimate(median=80.0),) * 2
    )
    assert artifact("train_population_mean").predict(request()) == (None, None)


def test_saved_artifact_roundtrip_preserves_inference_and_refuses_bad_state():
    fitted = artifact("train_population_mean", [row("train-a", -1, 60.0)])
    loaded = BaselineArtifact.model_validate_json(fitted.model_dump_json())
    assert loaded.predict(request()) == fitted.predict(request())
    assert loaded.model_id == "train-population-mean-v1"
    with pytest.raises(ValidationError):
        BaselineArtifact.model_validate({**fitted.model_dump(), "population_mean": None})
    with pytest.raises(ValidationError):
        BaselineConfig(method="last_valid", metric="steps", aggregation="mean")


def test_saved_model_cannot_be_replayed_before_its_fit_cutoff():
    fitted = artifact("train_population_mean", [row("train-a", -1, 60.0)])
    with pytest.raises(ValueError, match="fit cutoff"):
        fitted.predict(request(cutoff=BASE - HOUR))
