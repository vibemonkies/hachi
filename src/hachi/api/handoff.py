"""#16 handoff check: API forecasts must equal the model owner's own inference.

For every origin in a real evaluation packet, the check asks a running API for the same
forecast over HTTP and compares it with (1) the predictions the evaluator saved in the
packet and (2) a fresh direct inference that hands the loaded artifact to
`hachi.evaluation.evaluate_forecast` at a one-origin split. Neither reference reuses the
API's input builder. Output is aggregate: counts, differences and identities, no values.

    python -m hachi.api handoff --base-url http://127.0.0.1:8716 --packet <evaluations/model>
"""

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from hachi.contracts.api import HealthStatus, ReportJob
from hachi.contracts.base import SCHEMA_VERSION
from hachi.contracts.manifests import RunManifest, SplitManifest, TimeWindow
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


def api_medians(job: ReportJob) -> dict[datetime, float] | None:
    result = job.result.root if job.result is not None else None
    if not isinstance(result, PhysiologyForecastResult):
        return None
    (series,) = result.forecast.series
    return {p.interval_start_utc: p.median for p in series.points}


def expected_medians(
    cutoff: datetime, estimates: tuple[ForecastEstimate | None, ...] | None
) -> dict[datetime, float]:
    return {cutoff + i * HOUR: e.median for i, e in enumerate(estimates or ()) if e is not None}


class Tally:
    """Aggregate agreement between API points and a reference's points."""

    def __init__(self) -> None:
        self.compared = 0
        self.mismatched = 0
        self.missing_in_reference = 0
        self.max_difference = 0.0

    def add(self, shown: dict[datetime, float], reference: dict[datetime, float]) -> None:
        for start, median in shown.items():
            if start not in reference:
                self.missing_in_reference += 1
                continue
            difference = abs(median - reference[start])
            self.compared += 1
            self.mismatched += difference != 0.0
            self.max_difference = max(self.max_difference, difference)

    def summary(self) -> dict[str, Any]:
        return {
            "points_compared": self.compared,
            "points_mismatched": self.mismatched,
            "api_points_without_reference": self.missing_in_reference,
            "max_abs_difference": self.max_difference,
        }

    @property
    def agrees(self) -> bool:
        return self.compared > 0 and not self.mismatched and not self.missing_in_reference


# HTTP -----------------------------------------------------------------------------------


def _call(base_url: str, method: str, path: str, body: Any = None) -> tuple[int, bytes]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base_url.rstrip("/") + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def request_forecast(base_url: str, body: dict, timeout: float = 300.0) -> ReportJob:
    status, payload = _call(base_url, "POST", "/v1/reports", body)
    if status not in (200, 202):
        raise RuntimeError(f"POST /v1/reports answered {status}")
    job = ReportJob.model_validate_json(payload)
    deadline = time.monotonic() + timeout
    while job.state != "completed":
        if time.monotonic() > deadline:
            raise TimeoutError("report job did not complete")
        time.sleep(0.2)
        status, payload = _call(base_url, "GET", f"/v1/reports/{job.report_id}")
        job = ReportJob.model_validate_json(payload)
    return job


# Packet ---------------------------------------------------------------------------------


def load_packet(packet: Path) -> tuple[RunManifest, dict[str, Any]]:
    """The run manifest and evaluation document, after checking the packet's own hashes."""
    hashes = json.loads((packet / "sha256.json").read_bytes())
    for name, digest in hashes.items():
        if hashlib.sha256((packet / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"packet file {name} does not match sha256.json")
    run = RunManifest.model_validate_json((packet / "run.json").read_bytes())
    return run, json.loads((packet / "evaluation.json").read_bytes())


def run_handoff(
    base_url: str, packet: Path, served: ServedArtifact, subjects: dict[str, SubjectData]
) -> dict[str, Any]:
    run, evaluation = load_packet(packet)
    if run.artifact != served.ref:
        raise ValueError("the packet's run names a different artifact than the one served")
    _, payload = _call(base_url, "GET", "/healthz")
    health = HealthStatus.model_validate_json(payload)
    vs_packet, vs_direct = Tally(), Tally()
    outcomes: Counter[str] = Counter()
    provenance_mismatches = 0
    for prediction in evaluation["predictions"]:
        origin = prediction["origin"]
        cutoff = datetime.fromisoformat(origin["cutoff"])
        horizon = len(origin["targets"])
        job = request_forecast(
            base_url,
            {
                "schema_version": SCHEMA_VERSION,
                "subject_id": origin["subject_id"],
                "as_of": origin["cutoff"],
                "task": "physiology_forecast",
                "resolution": "hour",
                "horizon_hours": horizon,
                "metrics": [served.metric],
            },
        )
        result = job.result.root if job.result is not None else None
        outcomes[
            result.status
            if result is None or result.status != "unavailable"
            else f"unavailable:{result.reason_code}"
        ] += 1
        packet_estimates = tuple(
            None if e is None else ForecastEstimate.model_validate(e)
            for e in prediction["estimates"]
        )
        reference = expected_medians(cutoff, packet_estimates)
        shown = api_medians(job)
        if shown is None:
            outcomes["agreed_abstention" if not reference else "api_missing_forecast"] += 1
            continue
        if (
            result.provenance.artifact != run.artifact
            or result.provenance.dataset_snapshot != run.dataset_snapshot
        ):
            provenance_mismatches += 1
        vs_packet.add(shown, reference)
        direct = direct_inference(served, subjects[origin["subject_id"]], cutoff, horizon)
        vs_direct.add(shown, expected_medians(cutoff, direct))
    agrees = (
        vs_packet.agrees
        and vs_direct.agrees
        and not provenance_mismatches
        and not outcomes["api_missing_forecast"]
        and served.ref in health.artifacts
    )
    return {
        "agrees": agrees,
        "api": {"git_sha": health.git_sha, "status": health.status},
        "artifact": served.ref.model_dump(),
        "dataset_snapshot": run.dataset_snapshot.model_dump(),
        "packet_run_id": run.run_id,
        "origins": len(evaluation["predictions"]),
        "outcomes": dict(sorted(outcomes.items())),
        "provenance_mismatches": provenance_mismatches,
        "vs_packet_predictions": vs_packet.summary(),
        "vs_direct_inference": vs_direct.summary(),
    }
