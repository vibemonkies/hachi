"""#16 handoff check: an API forecast must equal direct inference through the evaluator.

The direct side does not reuse the API's input builder. It hands the loaded artifact to
`hachi.evaluation.evaluate_forecast` with a one-origin split at the same cutoff, so the
evaluator itself selects the causal history window, applies the minimum-history rule and
calls the model. The comparison reports counts, differences and identities only.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from hachi.contracts.api import ReportJob
from hachi.contracts.base import SCHEMA_VERSION
from hachi.contracts.manifests import SplitManifest, TimeWindow
from hachi.contracts.results import PhysiologyForecastResult
from hachi.evaluation import ForecastEstimate, evaluate_forecast

from .artifacts import ServedArtifact
from .sources import SubjectData

HOUR = timedelta(hours=1)


def direct_inference(
    served: ServedArtifact, subject: SubjectData, cutoff: datetime, horizon_hours: int
) -> tuple[ForecastEstimate | None, ...] | None:
    """The evaluator's prediction at one origin, or None if it excluded the origin."""
    if cutoff.minute or cutoff.second or cutoff.microsecond:
        raise ValueError("the evaluator takes whole-hour cutoffs")
    if served.serving.input == "hourly_features":
        assert served.serving.feature_policy is not None
        history: list = subject.hourly_features(served.serving.feature_policy, cutoff)
    else:
        history = subject.observations(served.metric, cutoff)
    split = SplitManifest(
        schema_version=SCHEMA_VERSION,
        manifest_id="handoff-one-origin",
        created_at_utc=cutoff,
        dataset_snapshot=subject.snapshot,
        task="physiology_forecast",
        fold=None,
        n_folds=None,
        train_subjects=["handoff-unused-train"],
        validation_subjects=[subject.subject_id],
        test_subjects=[],
        exclusions=[],
        lookback_hours=served.split.lookback_hours,
        horizon_hours=horizon_hours,
        embargo_hours=0,
        cutoff_stride_hours=horizon_hours,
        min_history_hours=served.split.min_history_hours,
        evaluation_window=TimeWindow(start_utc=cutoff, end_utc=cutoff + horizon_hours * HOUR),
        seed=served.split.seed,
        test_opened_at_utc=None,
    )
    result = evaluate_forecast(
        split, history, [], lambda _training: served.model.predict, served.evaluation
    )
    return result.predictions[0].estimates if result.predictions else None


@dataclass(frozen=True)
class Comparison:
    points_compared: int
    abstained_hours: int
    max_abs_difference: float | None
    provenance_matches: bool
    agrees: bool


def compare(
    job: ReportJob,
    served: ServedArtifact,
    subject: SubjectData,
    direct: tuple[ForecastEstimate | None, ...] | None,
) -> Comparison:
    result = job.result.root if job.result is not None else None
    if not isinstance(result, PhysiologyForecastResult):
        return Comparison(
            0, 0, None, False, agrees=direct is None or all(e is None for e in direct)
        )
    series = next(s for s in result.forecast.series if s.metric == served.metric)
    by_start = {p.interval_start_utc: p.median for p in series.points}
    cutoff = result.as_of
    expected = {cutoff + i * HOUR: e.median for i, e in enumerate(direct or ()) if e is not None}
    shown = {start: by_start[start] for start in by_start}
    differences = [abs(shown[t] - expected[t]) for t in shown if t in expected]
    provenance = result.provenance
    provenance_matches = (
        provenance.artifact == served.ref and provenance.dataset_snapshot == subject.snapshot
    )
    agrees = (
        provenance_matches
        and set(shown) <= set(expected)
        and bool(differences)
        and max(differences) == 0.0
    )
    return Comparison(
        points_compared=len(differences),
        abstained_hours=sum(e is None for e in direct or ()),
        max_abs_difference=max(differences) if differences else None,
        provenance_matches=provenance_matches,
        agrees=agrees,
    )
