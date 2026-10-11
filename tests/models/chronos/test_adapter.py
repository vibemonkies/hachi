from datetime import timedelta

import pytest
from pydantic import ValidationError

from hachi.contracts.manifests import TimeWindow
from hachi.contracts.tables import Observation
from hachi.evaluation import ForecastEstimate, ForecastInput
from hachi.models.chronos import (
    AdapterLog,
    ChronosConfig,
    UnsupportedInput,
    build_request,
    estimates,
)
from hachi.models.chronos.inference import request_id

from .conftest import BASE, HOUR, feature

NINE = (0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)


def request(history, *, cutoff=BASE, steps=(0, 1), subject="synthetic-0") -> ForecastInput:
    return ForecastInput(
        subject,
        cutoff,
        tuple(
            TimeWindow(start_utc=cutoff + s * HOUR, end_utc=cutoff + (s + 1) * HOUR) for s in steps
        ),
        tuple(history),
    )


def test_context_is_a_regular_grid_ending_at_the_cutoff(chronos):
    history = [feature("synthetic-0", h, 60.0 + h) for h in (-9, -6, -4, -1)]
    built = build_request(request(history, steps=(2, 3, 4)), chronos)
    assert built is not None
    # Six hours ending at the cutoff; absent hours stay null; older rows fall outside.
    assert built.context == (54.0, None, 56.0, None, None, 59.0)
    assert built.steps == (2, 3, 4)
    assert built.prediction_length == 5
    assert built.request_id == request_id(list(built.context), 5)
    assert set(built.row()) == {"request_id", "context", "prediction_length"}


def test_identity_ignores_subject_and_cutoff_but_not_content(chronos):
    first = build_request(request([feature("synthetic-0", h, 61.0) for h in (-3, -2)]), chronos)
    shifted = build_request(
        request(
            [feature("synthetic-5", h, 61.0) for h in (1, 2)],
            cutoff=BASE + 4 * HOUR,
            subject="synthetic-5",
        ),
        chronos,
    )
    changed = build_request(request([feature("synthetic-0", h, 62.0) for h in (-3, -2)]), chronos)
    assert first is not None and shifted is not None and changed is not None
    assert first.request_id == shifted.request_id
    assert first.request_id != changed.request_id


def test_short_context_abstains(chronos):
    assert build_request(request([feature("synthetic-0", -1, 60.0)]), chronos) is None


def test_refuses_rows_unavailable_at_the_cutoff(chronos):
    late = feature("synthetic-0", -1, 60.0, delay_hours=2)
    with pytest.raises(ValueError, match="not available"):
        build_request(request([feature("synthetic-0", -2, 60.0), late]), chronos)


def test_refuses_other_channels_and_raw_observations(chronos):
    steps = feature("synthetic-0", -2, 100.0, metric="steps")
    with pytest.raises(UnsupportedInput, match="univariate"):
        build_request(request([feature("synthetic-0", -1, 60.0), steps]), chronos)
    raw = Observation(
        dataset_id="synthetic-chronos",
        subject_id="synthetic-0",
        record_id="raw-1",
        source_kind="research_device",
        source_id="synthetic-device",
        device_model=None,
        metric="heart_rate",
        unit="bpm",
        value=60.0,
        start_utc=BASE - HOUR,
        end_utc=BASE - HOUR + timedelta(minutes=1),
        available_at_utc=BASE - HOUR + timedelta(minutes=1),
        availability="observed",
        availability_rule=None,
        tz_name="UTC",
        utc_offset_minutes=0,
        tz_provenance="dataset_documentation",
    )
    with pytest.raises(UnsupportedInput, match="raw observations"):
        build_request(request([raw]), chronos)


def test_refuses_unaligned_cutoffs_and_targets(chronos):
    history = [feature("synthetic-0", h, 60.0) for h in (-3, -2)]
    with pytest.raises(UnsupportedInput, match="hour-aligned"):
        build_request(request(history, cutoff=BASE + timedelta(minutes=30)), chronos)
    past = ForecastInput(
        "synthetic-0", BASE, (TimeWindow(start_utc=BASE - HOUR, end_utc=BASE),), tuple(history)
    )
    with pytest.raises(UnsupportedInput, match="at or after the cutoff"):
        build_request(past, chronos)
    with pytest.raises(UnsupportedInput, match="output limit"):
        build_request(request(history, steps=(1024,)), chronos)


def test_config_refuses_covariates_and_bad_limits(chronos):
    data = chronos.model_dump()
    with pytest.raises(ValidationError):
        ChronosConfig.model_validate({**data, "covariates": "future"})
    with pytest.raises(ValidationError):
        ChronosConfig.model_validate({**data, "context_hours": 8193})
    with pytest.raises(ValidationError, match="fit inside"):
        ChronosConfig.model_validate({**data, "min_context_values": 7})
    with pytest.raises(ValidationError, match="aggregation"):
        ChronosConfig.model_validate({**data, "aggregation": "sum"})
    assert chronos.nominal_coverage == 0.8


def test_estimates_rearrange_crossings_and_clip_to_metric_bounds(chronos):
    log = AdapterLog()
    rows = [
        [50.0, 55.0, 58.0, 59.0, 60.0, 61.0, 62.0, 65.0, 70.0],
        [50.0, 55.0, 61.0, 59.0, 60.0, 61.0, 62.0, 65.0, 70.0],  # crossing at 0.1/0.25
        [-3.0, -1.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 400.0],  # outside 1..300 bpm
    ]
    output, kept = estimates(rows, NINE, (0, 1, 2), chronos, log)
    assert output[0] == ForecastEstimate(median=60.0, lower=58.0, upper=62.0)
    assert output[1] == ForecastEstimate(median=61.0, lower=59.0, upper=62.0)
    assert output[2] == ForecastEstimate(median=2.0, lower=1.0, upper=4.0)
    assert kept[2][0] == 1.0 and kept[2][-1] == 300.0
    assert log.counts == {"rearranged_steps": 1, "clipped_quantiles": 4}


def test_estimates_require_the_configured_levels(chronos):
    with pytest.raises(ValueError, match="not among"):
        estimates([[60.0, 61.0, 62.0]], (0.25, 0.5, 0.75), (0,), chronos)


def test_extended_builder_adds_longer_context_and_past_steps(chronos):
    from hachi.data.pmdata import FeatureBin
    from hachi.evaluation.context import ContextPolicy, context_index
    from hachi.evaluation.features import HourlyFeaturePolicy
    from hachi.models.chronos.adapter import extended_builder

    hr = [feature("synthetic-0", h, 60.0 + h % 7) for h in range(-12, 0) if h != -9]
    steps = [feature("synthetic-0", h, 100.0 + h, metric="steps") for h in range(-12, 0)]
    policies = [
        HourlyFeaturePolicy(
            metric=m,
            aggregation=a,
            min_coverage=0.5,
            min_observed_count=30,
            availability_rule="synthetic-final-at-bin-end",
        )
        for m, a in (("heart_rate", "mean"), ("steps", "sum"))
    ]
    bins = [FeatureBin(f.aggregate, f.available_at_utc) for f in (*hr, *steps)]
    index = context_index(bins, ContextPolicy(hours=12, channels=policies))
    harness = request([r for r in hr if r.start_utc >= BASE - 6 * HOUR])
    longer = extended_builder(chronos, index, context_hours=12, harness_lookback_hours=6)(harness)
    assert longer is not None and len(longer.context) == 12 and longer.context[3] is None
    assert longer.context[-6:] == build_request(harness, chronos).context
    covariate = extended_builder(
        chronos, index, context_hours=6, harness_lookback_hours=6, covariates=["steps"]
    )(harness)
    assert covariate is not None and covariate.row()["past_covariates"] == {
        "steps": [94.0, 95.0, 96.0, 97.0, 98.0, 99.0]
    }
    assert covariate.request_id != build_request(harness, chronos).request_id
    short = request([r for r in hr if r.start_utc >= BASE - 3 * HOUR])
    with pytest.raises(ValueError, match="disagrees"):
        extended_builder(chronos, index, context_hours=12, harness_lookback_hours=6)(short)
    with pytest.raises(ValueError, match="other channels"):
        extended_builder(
            chronos, index, context_hours=6, harness_lookback_hours=6, covariates=["heart_rate"]
        )
