"""Causal nightly physiology/anomaly features through #9's admitted native source interface."""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path

from hachi.data.clinical.config import registry_admission
from hachi.data.clinical.snapshot import check_admitted, read_table
from hachi.evaluation.serialization import document_sha256
from hachi.models.baselines.nightly import NightlyRequest
from hachi.models.baselines.robust import (
    DeviationScore,
    NightlyRest,
    nightly_deviation,
)
from hachi.models.baselines.stanford.rest import StanfordRestResult, stanford_nightly_rest
from hachi.models.baselines.stanford.source import phase1_members, read_native_nights

from .data import FeaturePoint, FeatureSet
from .protocol import Protocol

REST_NAMES = ("prior_night_rest_bpm", "prior_night_supported_quiet_minutes")
ANOMALY_NAMES = (
    "prior_night_robust_z",
    "prior_night_deviation_score",
    "causal_baseline_rest_bpm",
    "causal_baseline_scale_bpm",
    "causal_baseline_nights",
)


def causal_features(
    current: StanfordRestResult,
    history: Sequence[NightlyRest],
    surveys: Mapping[date, str],
    cutoff: datetime,
    protocol: Protocol,
) -> tuple[tuple[float | None, ...], tuple[float | None, ...], str]:
    """Only previously completed, observed symptom-free survey nights fit personal rest."""
    baseline = [
        n
        for n in history
        if surveys.get(n.local_date) == "symptom_free"
        and datetime.combine(n.local_date + timedelta(days=1), time(), cutoff.tzinfo) <= cutoff
    ]
    result = nightly_deviation(current.night, baseline, protocol.robust, cutoff=cutoff)
    rest = (
        current.night.rhr_bpm,
        current.night.observed_zero_step_minutes if current.status == "observed" else None,
    )
    if isinstance(result, DeviationScore):
        anomaly = (
            result.robust_z,
            result.score,
            result.baseline_median_bpm,
            result.scale_bpm,
            float(result.baseline_nights),
        )
        return rest, anomaly, "scored"
    return rest, (None,) * len(ANOMALY_NAMES), result.reason


def build_features(
    snapshot: Path, archive: Path, subjects: Sequence[str], protocol: Protocol
) -> tuple[dict[str, FeatureSet], dict[str, int]]:
    """Read only requested development subjects; no outcome/test fields enter feature values."""
    admission = registry_admission(protocol.dataset_id)
    admitted = admission.files["COVID-19-Wearables.zip"]
    check_admitted(archive, admitted)
    members = phase1_members(archive)
    cutoffs: dict[str, set[datetime]] = defaultdict(set)
    # Eligibility selects extraction requests, but not feature values. All families
    # evaluate identical labeled windows, including missing wearable inputs.
    for r in read_table(snapshot, "onset_windows", subjects).to_pylist():
        if any(r[f"onset_{h}h"] in {"positive", "negative"} for h in protocol.horizons_hours):
            cutoffs[r["subject_id"]].add(r["cutoff_utc"])
    surveys: dict[str, dict[date, str]] = defaultdict(dict)
    for r in read_table(snapshot, "surveys", subjects).to_pylist():
        surveys[r["subject_id"]][r["local_date"]] = r["state"]
    rest_points, anomaly_points, causal_hashes = [], [], []
    counts: Counter[str] = Counter()
    for subject, times in sorted(cutoffs.items()):
        first = min(times).date() - timedelta(days=protocol.robust.baseline_days + 1)
        last = max(times).date() - timedelta(days=1)
        native = read_native_nights(archive, members, subject, first, last)
        counts.update(native.counts)
        history: list[NightlyRest] = []
        day = first
        while day <= last:
            cutoff = datetime.combine(day + timedelta(days=1), time(), min(times).tzinfo)
            current = stanford_nightly_rest(
                native.heart_rate.get(day, ()),
                native.steps.get(day, ()),
                NightlyRequest(
                    dataset_id=protocol.dataset_id,
                    subject_id=subject,
                    local_date=day,
                    tz_name="UTC",
                    cutoff=cutoff,
                ),
                protocol.rest,
            )
            if cutoff in times:
                rest, anomaly, status = causal_features(
                    current, history, surveys[subject], cutoff, protocol
                )
                counts["eligible_subject_cutoffs"] += 1
                counts[f"anomaly:{status}"] += 1
                counts[f"rest:{current.status}"] += 1
                # Point at the requested cutoff prevents the previous night's
                # missingness being silently replaced with an older observed night.
                ready = max(cutoff, current.night.available_at_utc)
                rest_points.append(
                    FeaturePoint(subject_id=subject, at=cutoff, available_at=ready, values=rest)
                )
                anomaly_points.append(
                    FeaturePoint(subject_id=subject, at=cutoff, available_at=ready, values=anomaly)
                )
                causal_hashes.append(current.causal_input_sha256)
            history.append(current.night)
            day += timedelta(days=1)
    provenance = document_sha256(
        {
            "archive_sha256": admitted.sha256,
            "rest": protocol.rest,
            "robust": protocol.robust,
            "baseline_survey_rule": "previously-completed-symptom-free-days-only",
            "causal_inputs": causal_hashes,
        }
    )
    return {
        "nightly-rest": FeatureSet(
            feature_names=REST_NAMES,
            provenance_sha256=provenance,
            fit_subjects=(),
            clock=protocol.clock,
            points=tuple(rest_points),
        ),
        "anomaly-derived": FeatureSet(
            feature_names=ANOMALY_NAMES,
            provenance_sha256=provenance,
            fit_subjects=(),
            clock=protocol.clock,
            points=tuple(anomaly_points),
        ),
    }, dict(sorted(counts.items()))
