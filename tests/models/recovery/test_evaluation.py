import math

from hachi.models.recovery.evaluation import calibration, compare, observable_at, supported_horizon
from hachi.models.recovery.survival import Observation, SurvivalModel


def model(h=0.2):
    return SurvivalModel((math.log(h / (1 - h)),), (), (), False, 14, True, 0)


def test_calibration_identification_preserves_unknown_outcomes():
    rows = [
        Observation("a", "1", (), 2, 4),
        Observation("b", "2", (), None, 2),
        Observation("c", "3", (), 8, 9),
    ]
    assert [observable_at(r, 3) for r in rows] == [None, None, 0]
    result = calibration(rows, model(), 3)
    assert result["observed_resolution_fraction_bounds"] == [0, 2 / 3]
    assert result["identified_outcomes"] == 1
    assert result["brier_identification_bounds"][0] < result["brier_identification_bounds"][1]


def test_support_counts_people_not_repeated_episodes():
    rows = [Observation("a", str(i), (), None, 14) for i in range(10)]
    rows += [Observation("b", "b", (), None, 3)]
    assert supported_horizon(rows, 14, 2) == 3


def test_known_at_risk_support_does_not_treat_wide_event_interval_as_unresolved():
    rows = [Observation("a", "e1", (), 2, 20), Observation("b", "e2", (), None, 20)]
    assert supported_horizon(rows, 14, 2, known_at_risk=True) == 1


def test_cluster_bootstrap_and_uninformative_interval_exclusion():
    rows = [
        Observation("a", "1", (), 1, 20),
        Observation("a", "2", (), 2, 3),
        Observation("b", "3", (), None, 7),
    ]
    result, paired = compare(rows, model(), model(), 7, bootstrap=100, seed=42)
    assert result["excluded_no_information_at_horizon"] == 1
    assert result["conditional_minus_baseline_nll_ci95"] == [0, 0]
    assert result["subjects"] == 2
    assert len(paired) == 2
