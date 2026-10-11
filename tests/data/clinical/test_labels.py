"""The label engine against hand-built timelines: every definition in definitions.toml."""

from datetime import date, timedelta

import pytest

from hachi.data.clinical.labels import (
    DayRange,
    IllnessReport,
    SubjectInput,
    TestDay,
    label_subject,
)

from .conftest import DEFS

D = date(2024, 1, 1)


def d(n: int) -> date:
    return D + timedelta(days=n)


def one(n: int) -> DayRange:
    return DayRange(d(n), d(n))


def free(*days: int) -> dict:
    return {d(n): "symptom_free" for n in days}


def ill(*days: int) -> dict:
    return {d(n): "symptomatic" for n in days}


def subject(span=(0, 120), illnesses=(), surveys=None, self_report=False) -> SubjectInput:
    return SubjectInput(
        "S1", DayRange(d(span[0]), d(span[1])), list(illnesses), surveys or {}, self_report
    )


def window(labels, n):
    return next(w for w in labels.windows if w.cutoff == d(n))


def test_horizons_on_the_midnight_grid():
    out = label_subject(subject(illnesses=[IllnessReport("covid19", [one(50)])]), DEFS)
    assert DEFS.onset.horizons_hours == [24, 48, 72]
    assert window(out, 50).onset[0] == "positive"  # onset during the cutoff's own day
    assert window(out, 49).onset == ("unknown_no_survey", "positive", "positive")
    assert window(out, 48).onset == ("unknown_no_survey", "unknown_no_survey", "positive")
    assert window(out, 50).onset_episode[0] == "S1-e1"


def test_ongoing_episode_and_washouts():
    surveys = {**ill(*range(50, 55)), **free(55, 56)}
    out = label_subject(subject(illnesses=[IllnessReport("x", [one(50)])], surveys=surveys), DEFS)
    sustained = out.episodes[0].endpoints["sustained_symptom_free"]
    assert sustained.status == "resolved"
    assert sustained.resolution == DayRange(d(55), d(55))
    assert window(out, 51).onset[0] == "excluded_ongoing_episode"
    assert window(out, 55).onset[0] == "excluded_ongoing_episode"
    washout = DEFS.onset.washout_after_resolution_days
    assert window(out, 55 + washout).onset[0] == "excluded_washout"
    assert window(out, 56 + washout).onset[0] == "unknown_no_survey"

    censored = label_subject(subject(illnesses=[IllnessReport("x", [one(50)])]), DEFS)
    limit = DEFS.onset.washout_after_censored_onset_days
    assert window(censored, 50 + limit).onset[0] == "excluded_washout"
    assert window(censored, 51 + limit).onset[0] == "unknown_no_survey"


def test_negative_needs_a_symptom_free_survey_every_day():
    surveys = {**free(10, 11, 12), **ill(30), **free(31)}
    out = label_subject(subject(surveys=surveys), DEFS)
    assert window(out, 10).onset == ("negative", "negative", "negative")
    assert window(out, 11).onset == ("negative", "negative", "unknown_no_survey")
    assert window(out, 30).onset[0] == "uncertain_unexplained_symptoms"
    assert window(out, 31).onset[0] == "negative"
    assert window(out, 5).onset[0] == "unknown_no_survey"


def test_windows_past_follow_up_are_unknown():
    out = label_subject(subject(span=(0, 20), surveys=free(*range(0, 21))), DEFS)
    assert window(out, 20).onset == ("negative", *["unknown_follow_up_ended"] * 2)
    assert out.windows[0].cutoff == d(1)  # a cutoff needs an earlier day for features


def test_partial_onset_interval_is_uncertain():
    out = label_subject(
        subject(illnesses=[IllnessReport("x", [DayRange(d(49), d(50))])], surveys=free(48)), DEFS
    )
    assert window(out, 50).onset[0] == "uncertain_partial_onset"
    assert window(out, 49).onset[:2] == ("uncertain_partial_onset", "positive")


def test_test_links_and_test_target():
    positive = TestDay(d(52), "sars_cov_2", "pcr", "positive")
    illness = IllnessReport("covid19", [one(50)], (), [positive])
    out = label_subject(subject(span=(0, 200), illnesses=[illness]), DEFS)
    assert out.tests[0].episode_id == "S1-e1"
    assert out.episodes[0].confidence == "confirmed"
    assert window(out, 52).test[0] == "positive_test"
    assert window(out, 50).test[2] == "positive_test"
    assert window(out, 50).test[:2] == ("no_reported_positive_test",) * 2
    assert window(out, 53).test[0] == "excluded_recent_positive"
    gap = DEFS.test.exclude_days_after_positive
    assert window(out, 52 + gap).test[0] == "excluded_recent_positive"
    assert window(out, 53 + gap).test[0] == "no_reported_positive_test"


def test_a_test_is_never_an_onset():
    late = TestDay(d(100), "sars_cov_2", "unknown", "positive")
    illness = IllnessReport("covid19", [one(50)], (), [late])
    out = label_subject(subject(span=(0, 160), illnesses=[illness]), DEFS)
    assert out.tests[0].episode_id is None
    assert out.issues["positive_test_unlinked"] == 1
    before = DEFS.onset.infection_without_onset_days_before
    assert window(out, 99 - before).onset[0] == "unknown_no_survey"
    assert window(out, 100 - before).onset[0] == "excluded_infection_without_onset"
    assert window(out, 100).onset[0] == "excluded_infection_without_onset"
    assert "positive" not in window(out, 100).onset
    # The illness's only test is not this episode's, so the episode is not called COVID-19.
    assert out.episodes[0].category == "unspecified_illness"
    assert out.episodes[0].confidence == "probable"


def test_asymptomatic_positive_has_no_episode():
    test = TestDay(d(40), "sars_cov_2", "unknown", "positive")
    out = label_subject(subject(illnesses=[IllnessReport("covid19", [], (), [test])]), DEFS)
    assert out.episodes == []
    assert out.issues["illness_without_onset"] == 1
    assert window(out, 40).onset[0] == "excluded_infection_without_onset"


def test_undated_illness_blocks_every_window():
    out = label_subject(subject(illnesses=[IllnessReport("other", [])], surveys=free(10, 11)), DEFS)
    assert {w.onset[0] for w in out.windows} == {"excluded_undated_illness"}


def test_relapse_merging():
    merged = label_subject(subject(illnesses=[IllnessReport("x", [one(50), one(60)])]), DEFS)
    assert len(merged.episodes) == 1 and merged.episodes[0].reported_onsets == 2
    split = label_subject(
        subject(illnesses=[IllnessReport("x", [one(50), one(60)], [d(55)])], self_report=True),
        DEFS,
    )
    assert len(split.episodes) == 2
    far = label_subject(subject(illnesses=[IllnessReport("x", [one(50), one(80)])]), DEFS)
    assert len(far.episodes) == 2


def test_sustained_interval_censoring_and_next_onset():
    surveys = {**ill(50, 52), **free(55, 56)}  # a gap between the last ill and first free days
    out = label_subject(subject(illnesses=[IllnessReport("x", [one(50)])], surveys=surveys), DEFS)
    r = out.episodes[0].endpoints["sustained_symptom_free"]
    assert r.resolution == DayRange(d(53), d(55)) and r.follow_up_last == d(56)

    no_run = label_subject(
        subject(illnesses=[IllnessReport("x", [one(50)])], surveys={**ill(51), **free(53)}), DEFS
    )
    r = no_run.episodes[0].endpoints["sustained_symptom_free"]
    assert (r.status, r.reason, r.follow_up_last) == ("right_censored", "no_qualifying_run", d(53))

    none = label_subject(subject(illnesses=[IllnessReport("x", [one(50)])]), DEFS)
    r = none.episodes[0].endpoints["sustained_symptom_free"]
    assert (r.reason, r.follow_up_last) == ("no_follow_up", d(50))

    # A symptom-free run that reaches the next episode's onset does not resolve the first.
    blocked = label_subject(
        subject(illnesses=[IllnessReport("x", [one(50), one(70)])], surveys=free(69, 70)), DEFS
    )
    assert blocked.episodes[0].endpoints["sustained_symptom_free"].status == "right_censored"


def test_self_reported_recovery_rules():
    def run(recoveries, surveys=None):
        out = label_subject(
            subject(
                illnesses=[IllnessReport("x", [one(50)], recoveries)],
                surveys=surveys,
                self_report=True,
            ),
            DEFS,
        )
        return out.episodes[0].endpoints["self_reported_recovery"], out.issues

    accepted, _ = run([d(58)])
    assert accepted.status == "resolved" and accepted.resolution == DayRange(d(58), d(58))
    contradicted, issues = run([d(58)], ill(60))
    assert contradicted.reason == "rejected_contradicted_by_survey"
    assert issues["self_reported_recovery_rejected_contradicted_by_survey"] == 1
    late_symptoms, _ = run([d(58)], ill(58 + DEFS.recovery.contradiction_days + 1))
    assert late_symptoms.status == "resolved"
    latest, issues = run([d(55), d(65)])
    assert latest.resolution == DayRange(d(65), d(65))
    assert issues["self_reported_recovery_earlier_date_superseded"] == 1
    _, issues = run([d(40)])
    assert issues["self_reported_recovery_rejected_before_onset"] == 1


def test_infection_status_sets_confidence():
    def confidence(flag):
        illness = IllnessReport("rhinovirus_challenge", [one(2)], infection_confirmed=flag)
        return label_subject(subject(illnesses=[illness]), DEFS).episodes[0].confidence

    assert (confidence(True), confidence(False), confidence(None)) == (
        "confirmed",
        "uncertain",
        "probable",
    )


def test_unknown_periods_skip_surveys_and_episodes():
    out = label_subject(
        subject(span=(0, 30), illnesses=[IllnessReport("x", [one(20)])], surveys=free(5, 6)), DEFS
    )
    assert out.unknown == [DayRange(d(0), d(4)), DayRange(d(7), d(19)), DayRange(d(21), d(30))]


def test_day_ranges_are_ordered():
    with pytest.raises(ValueError):
        DayRange(d(2), d(1))


def test_off_midnight_cutoffs_keep_day_precision():
    from datetime import UTC, datetime

    from hachi.data.clinical.labels import classify

    out = label_subject(subject(illnesses=[IllnessReport("x", [one(50)])]), DEFS)
    tl = out.timeline

    def label(n, hour, h):
        cutoff = datetime(d(n).year, d(n).month, d(n).day, hour, tzinfo=UTC)
        return classify(tl, cutoff, h, DEFS)[0]

    assert label(49, 13, 24) == "uncertain_partial_onset"  # [49 13:00, 50 13:00) cuts day 50
    assert label(49, 13, 48) == "positive"
    assert label(50, 6, 24) == "uncertain_partial_onset"  # the cutoff falls inside the onset day
    assert label(51, 0, 24) == "excluded_washout"  # censored episode, nothing known after onset
    with pytest.raises(ValueError, match="UTC"):
        classify(tl, datetime(2024, 1, 1), 24, DEFS)
