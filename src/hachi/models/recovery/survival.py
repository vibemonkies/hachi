"""Discrete daily hazard likelihood; event dates are never imputed.

An interval [L, U] contributes S(L-1)-S(U), and right censoring at C
contributes S(C). Time zero is the end of an observed symptomatic day.
Future covariates are held at their landmark values, not silently forecast.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    subject: str
    episode: str
    covariates: tuple[float, ...]
    lower: int | None
    upper: int

    def __post_init__(self) -> None:
        if self.upper < 1 or (self.lower is not None and not 1 <= self.lower <= self.upper):
            raise ValueError("positive follow-up and a nonempty event interval are required")
        if not all(math.isfinite(x) for x in self.covariates):
            raise ValueError("covariates must be finite")


def _log_sigmoid(x: float) -> float:
    return -max(-x, 0) - math.log1p(math.exp(-abs(x)))


def _logsumexp(xs: list[float]) -> float:
    peak = max(xs)
    return peak + math.log(sum(math.exp(x - peak) for x in xs))


@dataclass(frozen=True)
class SurvivalModel:
    coefficients: tuple[float, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    conditional: bool
    supported_days: int
    converged: bool
    iterations: int

    def __post_init__(self) -> None:
        dimension = len(self.means) + 2 if self.conditional else 1
        if (
            len(self.coefficients) != dimension
            or len(self.scales) != len(self.means)
            or self.supported_days < 1
            or self.iterations < 0
            or not all(math.isfinite(x) for x in (*self.coefficients, *self.means, *self.scales))
            or any(s <= 0 for s in self.scales)
        ):
            raise ValueError("invalid recovery model dimensions/numerics/support")

    def design(self, day: int, covariates: tuple[float, ...]) -> tuple[float, ...]:
        if not self.conditional:
            return (1.0,)
        if len(covariates) != len(self.means):
            raise ValueError("predictors must match the frozen training schema")
        return (
            1.0,
            math.log(day),
            *((x - m) / s for x, m, s in zip(covariates, self.means, self.scales, strict=True)),
        )

    def survival(self, covariates: tuple[float, ...], days: int) -> tuple[float, ...]:
        if not 0 <= days <= self.supported_days:
            raise ValueError("requested horizon exceeds training follow-up support")
        log_s = 0.0
        curve = [1.0]
        for day in range(1, days + 1):
            eta = sum(
                b * x for b, x in zip(self.coefficients, self.design(day, covariates), strict=True)
            )
            log_s += _log_sigmoid(-eta)
            curve.append(math.exp(log_s))
        return tuple(curve)

    def quantiles(self, covariates: tuple[float, ...]) -> dict[str, int | None]:
        curve = self.survival(covariates, self.supported_days)
        return {
            str(q): next((d for d, s in enumerate(curve) if 1 - s >= q), None)
            for q in (0.25, 0.5, 0.75)
        }


def _score(model: SurvivalModel, row: Observation) -> tuple[float, list[float]]:
    """Stable log probability and analytic gradient for one censored observation."""
    dimension = len(model.coefficients)
    cumulative = [0.0] * dimension
    log_s = 0.0
    event_logs: list[float] = []
    event_scores: list[list[float]] = []
    for day in range(1, row.upper + 1):
        design = model.design(day, row.covariates)
        eta = sum(b * x for b, x in zip(model.coefficients, design, strict=True))
        log_h, log_one_minus = _log_sigmoid(eta), _log_sigmoid(-eta)
        hazard = math.exp(log_h)
        if row.lower is not None and day >= row.lower:
            event_logs.append(log_s + log_h)
            event_scores.append(
                [g + (1 - hazard) * x for g, x in zip(cumulative, design, strict=True)]
            )
        log_s += log_one_minus
        cumulative = [g - hazard * x for g, x in zip(cumulative, design, strict=True)]
    if row.lower is None:
        return log_s, cumulative
    log_p = _logsumexp(event_logs)
    gradient = [
        sum(
            math.exp(p - log_p) * score[j]
            for p, score in zip(event_logs, event_scores, strict=True)
        )
        for j in range(dimension)
    ]
    return log_p, gradient


def log_probability(model: SurvivalModel, row: Observation) -> float:
    if row.upper > model.supported_days:
        raise ValueError("scoring exceeds training follow-up support")
    return _score(model, row)[0]


def fit_survival(
    rows: list[Observation],
    *,
    conditional: bool,
    supported_days: int,
    ridge: float = 0.1,
    max_iterations: int = 3000,
    tolerance: float = 1e-6,
) -> SurvivalModel:
    """Fixed ridge model or constant training-cohort hazard; no label-based tuning.

    Minimize average censored negative log likelihood with backtracking descent.
    The intercept is unpenalized. Scaling sees only training participants.
    """
    if not rows or not any(r.lower is not None for r in rows):
        raise ValueError("training requires follow-up and at least one resolution")
    if supported_days < 1 or ridge < 0 or max_iterations < 1 or tolerance <= 0:
        raise ValueError("invalid fitting policy")
    dimension = len(rows[0].covariates)
    if any(len(r.covariates) != dimension or r.upper > supported_days for r in rows):
        raise ValueError("training rows must match schema and supported range")
    means = tuple(sum(r.covariates[j] for r in rows) / len(rows) for j in range(dimension))
    scales = tuple(
        max(1e-6, math.sqrt(sum((r.covariates[j] - means[j]) ** 2 for r in rows) / len(rows)))
        for j in range(dimension)
    )
    beta = (-2.0,) + (0.0,) * (dimension + 1) if conditional else (-2.0,)

    def objective(coefficients: tuple[float, ...]) -> tuple[float, list[float]]:
        model = SurvivalModel(coefficients, means, scales, conditional, supported_days, False, 0)
        scores = [_score(model, row) for row in rows]
        loss = -sum(p for p, _ in scores) / len(rows)
        loss += ridge * sum(b * b for b in coefficients[1:]) / 2
        gradient = [
            -sum(g[j] for _, g in scores) / len(rows) + (ridge * b if j else 0)
            for j, b in enumerate(coefficients)
        ]
        return loss, gradient

    converged = False
    for _iteration in range(1, max_iterations + 1):
        loss, gradient = objective(beta)
        norm = sum(g * g for g in gradient)
        if math.sqrt(norm) <= tolerance:
            converged = True
            break
        step = 1.0
        while step > 1e-12:
            candidate = tuple(b - step * g for b, g in zip(beta, gradient, strict=True))
            if objective(candidate)[0] <= loss - 1e-4 * step * norm:
                beta = candidate
                break
            step /= 2
        else:
            break
    return SurvivalModel(beta, means, scales, conditional, supported_days, converged, _iteration)


def truncate(row: Observation, days: int) -> Observation | None:
    """A straddling interval conveys survival only through its lower bound minus one.

    Never turn an event interval that extends beyond support into an exact event
    at the support boundary, or assert survival through its unknown portion.
    Return None for an interval with no positive known survival time at this horizon.
    """
    if days < 1:
        raise ValueError("a positive scoring horizon is required")
    if row.lower is not None and row.upper > days:
        if row.lower == 1:
            return None
        return Observation(row.subject, row.episode, row.covariates, None, min(days, row.lower - 1))
    return Observation(row.subject, row.episode, row.covariates, row.lower, min(days, row.upper))
