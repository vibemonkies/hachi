"""Causal personal-baseline features reuse the source-audited #9 adapter."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from hachi.models.baselines.nightly import NightlyRequest
from hachi.models.baselines.robust import NightlyRest
from hachi.models.baselines.stanford.rest import StanfordRestResult
from hachi.models.illness.protocol import load_protocol
from hachi.models.illness.stanford import causal_features

P = load_protocol(Path("configs/experiments/illness/phase1.toml"))


def night(day, bpm):
    start = datetime.combine(day, datetime.min.time(), UTC)
    return NightlyRest(
        subject_id="synthetic",
        local_date=day,
        tz_name="UTC",
        start_utc=start,
        end_utc=start + timedelta(hours=7),
        available_at_utc=start + timedelta(hours=7),
        rhr_bpm=bpm,
        observed_zero_step_minutes=60,
    )


def test_unknown_or_future_survey_cannot_enter_personal_baseline():
    today = date(2020, 1, 20)
    cutoff = datetime(2020, 1, 21, tzinfo=UTC)
    current = night(today, 70)
    result = StanfordRestResult(
        request=NightlyRequest(
            dataset_id=P.dataset_id,
            subject_id="synthetic",
            local_date=today,
            tz_name="UTC",
            cutoff=cutoff,
        ),
        policy=P.rest,
        night=current,
        status="observed",
        causal_input_sha256="a" * 64,
        counts={},
    )
    history = [night(today - timedelta(days=k), 60) for k in range(1, 8)]
    history += [night(today - timedelta(days=8), 200), night(today + timedelta(days=1), 200)]
    observed = {n.local_date: "symptom_free" for n in history[:7]}
    rest, anomaly, status = causal_features(result, history, observed, cutoff, P)
    assert rest == (70, 60)
    assert status == "scored"
    assert anomaly == (10, 10, 60, 1, 7)
    observed[today + timedelta(days=1)] = "symptom_free"
    assert causal_features(result, history, observed, cutoff, P)[1] == anomaly
    # Unknown past survey is not healthy; only six known free nights is cold start.
    observed.pop(history[0].local_date)
    assert causal_features(result, history, observed, cutoff, P)[2] == "cold_start"
