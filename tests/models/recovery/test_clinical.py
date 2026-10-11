from datetime import UTC, date, datetime, timedelta

import pytest

from hachi.models.recovery.clinical import ENDPOINT, SCALE, build_landmarks
from hachi.models.recovery.cohorts import CMU

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


@pytest.mark.parametrize(
    "tail_state,expected", [("symptom_free", 2), ("intermediate", 3), ("symptomatic", 3)]
)
def test_censor_bound_is_known_unresolved_not_last_answered_day(tail_state, expected):
    args = inputs()
    args[0][0].update(
        status="right_censored",
        reason="no_qualifying_run",
        follow_up_last_day=D + timedelta(days=5),
    )
    args[2].extend(
        [
            {
                "subject_id": "synthetic",
                "local_date": D + timedelta(days=4),
                "state": "symptomatic",
            },
            {"subject_id": "synthetic", "local_date": D + timedelta(days=5), "state": tail_state},
        ]
    )
    rows, _ = build_landmarks(*args)
    assert rows[0].observation.upper == expected


def test_free_tail_after_gap_cannot_prove_unresolved_inside_gap():
    args = inputs()
    args[0][0].update(
        status="right_censored",
        reason="no_qualifying_run",
        follow_up_last_day=D + timedelta(days=8),
    )
    args[2].extend(
        [
            {
                "subject_id": "synthetic",
                "local_date": D + timedelta(days=3),
                "state": "intermediate",
            },
            {
                "subject_id": "synthetic",
                "local_date": D + timedelta(days=8),
                "state": "symptom_free",
            },
        ]
    )
    assert build_landmarks(*args)[0][0].observation.upper == 1


def test_only_landmark_then_free_tail_has_zero_known_remaining_followup():
    args = inputs()
    args[0][0].update(
        status="right_censored",
        reason="no_qualifying_run",
        follow_up_last_day=D + timedelta(days=3),
    )
    args[2].append(
        {"subject_id": "synthetic", "local_date": D + timedelta(days=3), "state": "symptom_free"}
    )
    rows, audit = build_landmarks(*args)
    assert rows == []
    assert audit["excluded_no_future_follow_up"] == 1


def test_cmu_uses_jackson_score_without_severity_scale_substitution():
    args = inputs()
    args[3][0].update(scale=CMU.scale, jackson_adjusted=3.5, cold_or_flu=None)
    rows, _ = build_landmarks(*args, cohort=CMU)
    assert rows[0].observation.covariates == (3.5,)
    assert rows[0].source_scale == CMU.scale
    with pytest.raises(ValueError, match="scale"):
        build_landmarks(*args)
