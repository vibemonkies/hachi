import math

import pytest

from hachi.models.recovery.survival import (
    Observation,
    SurvivalModel,
    _score,
    fit_survival,
    log_probability,
    truncate,
)


def constant(hazard=0.2, days=20):
    return SurvivalModel((math.log(hazard / (1 - hazard)),), (), (), False, days, True, 0)


def test_interval_mass_and_right_censor_are_exact():
    model = constant()
    event = Observation("a", "e", (), 2, 5)
    censor = Observation("b", "e", (), None, 5)
    assert math.exp(log_probability(model, event)) == pytest.approx(0.8 - 0.8**5)
    assert math.exp(log_probability(model, censor)) == pytest.approx(0.8**5)
    assert log_probability(model, event) != log_probability(model, Observation("a", "e", (), 3, 3))


@pytest.mark.parametrize("lower", [None, 1, 3, 8])
def test_analytic_gradient_against_finite_difference(lower):
    model = SurvivalModel((-2.0, 0.1, -0.3), (0.0,), (1.0,), True, 10, True, 0)
    row = Observation("a", "e", (1.5,), lower, 8)
    _, gradient = _score(model, row)
    for j in range(3):
        plus, minus = list(model.coefficients), list(model.coefficients)
        plus[j] += 1e-5
        minus[j] -= 1e-5
        a = SurvivalModel(tuple(plus), model.means, model.scales, True, 10, True, 0)
        b = SurvivalModel(tuple(minus), model.means, model.scales, True, 10, True, 0)
        finite = (log_probability(a, row) - log_probability(b, row)) / 2e-5
        assert gradient[j] == pytest.approx(finite, abs=1e-7)


def test_training_cohort_constant_hazard_matches_closed_form():
    rows = [Observation(str(i), str(i), (), 2, 2) for i in range(4)]
    rows += [Observation(str(i), str(i), (), None, 5) for i in range(4, 8)]
    model = fit_survival(rows, conditional=False, supported_days=5)
    assert model.converged
    assert 1 - model.survival((), 1)[1] == pytest.approx(4 / 28, abs=1e-5)


def test_curve_quantiles_abstain_and_bounds():
    model = constant(hazard=0.01, days=5)
    assert list(model.survival((), 5)) == sorted(model.survival((), 5), reverse=True)
    assert all(q is None for q in model.quantiles(()).values())
    with pytest.raises(ValueError, match="support"):
        model.survival((), 6)


def test_straddling_interval_does_not_become_exact_or_survive_unknown_days():
    row = Observation("a", "e", (), 3, 12)
    assert truncate(row, 5) == Observation("a", "e", (), None, 2)
    assert truncate(row, 2) == Observation("a", "e", (), None, 2)
    assert truncate(Observation("a", "e", (), 1, 12), 5) is None


def test_numerical_stability_for_extreme_logits_and_wide_intervals():
    model = SurvivalModel((-1000.0,), (), (), False, 100, True, 0)
    assert math.isfinite(log_probability(model, Observation("a", "e", (), 1, 100)))
    model = SurvivalModel((1000.0,), (), (), False, 100, True, 0)
    assert log_probability(model, Observation("a", "e", (), None, 100)) == -100000
