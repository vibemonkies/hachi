from datetime import UTC, date, datetime, timedelta

import pytest

from hachi.models.recovery.clinical import ENDPOINT, SCALE, build_landmarks

D = date(2020, 1, 1)


def inputs():
    recovery = [
        {
            "subject_id": "synthetic",
            "episode_id": "synthetic-e",
            "endpoint": "sustained_symptom_free",
            "resolution_definition": ENDPOINT,
            "status": "resolved",
            "reason": "resolved",
            "onset_first_day": D,
            "follow_up_last_day": D + timedelta(days=12),
            "resolution_first_day": D + timedelta(days=6),
            "resolution_last_day": D + timedelta(days=11),
        }
    ]
    episodes = [{"subject_id": "synthetic", "onset_first_day": D}]
    surveys = [
        {"subject_id": "synthetic", "local_date": D + timedelta(days=2), "state": "symptomatic"}
    ]
    scores = [
        {
            "subject_id": "synthetic",
            "local_date": D + timedelta(days=2),
            "scale": SCALE,
            "available_at_utc": datetime(2020, 1, 4, tzinfo=UTC),
            "availability_rule": "survey-available-at-end-of-its-local-day",
            "symptom_count": 2,
            "max_severity": 3,
            "severity_sum": 5,
        }
    ]
    return recovery, episodes, surveys, scores, []


def test_landmark_uses_current_scores_and_keeps_future_interval():
    args = inputs()
    rows, audit = build_landmarks(*args)
    row = rows[0]
    assert row.observation.covariates == (2.0, 3.0, 5.0)
    assert (row.observation.lower, row.observation.upper) == (4, 9)
    assert not row.paired_wearable_day
    assert audit["eligible_resolved"] == 1
    args[0][0]["onset_first_day"] -= timedelta(days=3)
    args[1][0]["onset_first_day"] -= timedelta(days=3)
    assert build_landmarks(*args)[0][0].observation.covariates == row.observation.covariates
    args[3].append({**args[3][0], "local_date": D + timedelta(days=3), "severity_sum": 50})
    assert build_landmarks(*args)[0][0].observation.covariates == row.observation.covariates


def test_missing_scores_and_no_followup_are_excluded():
    args = inputs()
    args[3].clear()
    assert build_landmarks(*args)[1]["excluded_no_current_score"] == 1
    args[0][0]["reason"] = "no_follow_up"
    assert build_landmarks(*args)[1]["excluded_no_follow_up"] == 1


def test_unavailable_current_score_is_rejected():
    args = inputs()
    args[3][0]["available_at_utc"] += timedelta(days=1)
    with pytest.raises(ValueError, match="availability"):
        build_landmarks(*args)


def test_next_episode_cannot_supply_landmark_to_previous_episode():
    args = inputs()
    args[1].append({"subject_id": "synthetic", "onset_first_day": D + timedelta(days=1)})
    assert build_landmarks(*args)[1]["excluded_no_symptomatic_landmark"] == 1
