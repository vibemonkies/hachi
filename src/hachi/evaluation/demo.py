"""Reproducible synthetic-only evaluator walkthrough; no downloads or GPU work."""

import argparse
import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hachi.contracts.base import DatasetSnapshotRef
from hachi.contracts.manifests import ModelRef, RunManifest, SplitManifest, TimeWindow
from hachi.contracts.tables import Aggregate, Observation

from .artifacts import write_comparison_packet, write_packet
from .comparison import compare_forecasts
from .forecast import (
    EvaluationConfig,
    ForecastEstimate,
    ForecastInput,
    Predictor,
    TrainingPrefix,
    evaluate_forecast,
)
from .serialization import document_sha256
from .splits import partition_participants


def _last_value(_: TrainingPrefix) -> Predictor:
    """Illustrates the model hook, not issue #9's evaluated baseline suite."""

    def predict(request: ForecastInput) -> tuple[ForecastEstimate | None, ...]:
        value = ForecastEstimate(median=request.history[-1].value) if request.history else None
        return (value,) * len(request.targets)

    return predict


def _linear_prefix(_: TrainingPrefix) -> Predictor:
    """A second synthetic hook: extrapolate only the two most recent available samples."""

    def predict(request: ForecastInput) -> tuple[ForecastEstimate | None, ...]:
        if len(request.history) < 2:
            return (None,) * len(request.targets)
        previous, last = request.history[-2:]
        elapsed = (last.start_utc - previous.start_utc).total_seconds()
        if elapsed <= 0:
            return (None,) * len(request.targets)
        slope = (last.value - previous.value) / elapsed
        return tuple(
            ForecastEstimate(
                median=last.value + slope * (w.start_utc - last.start_utc).total_seconds()
            )
            for w in request.targets
        )

    return predict


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="new private packet directory")
    parser.add_argument("--paired", action="store_true", help="compare two synthetic model hooks")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    config = EvaluationConfig.model_validate_json(
        (root / "configs/evaluation/synthetic-hourly.json").read_text()
    )
    if config.data_mode != "synthetic":
        parser.error("this walkthrough generates synthetic data only")
    base = datetime(2026, 10, 10, 8, tzinfo=UTC)
    hour = timedelta(hours=1)
    subjects = [f"synthetic-{i}" for i in range(6)]
    observations: list[Observation] = []
    targets: list[Aggregate] = []
    for subject in subjects:
        for h in range(-4, 4):
            start = base + h * hour
            end = start + timedelta(minutes=15)
            value = 60.0 + max(h, 0)
            observations.append(
                Observation(
                    dataset_id="synthetic-cohort",
                    subject_id=subject,
                    record_id=f"{subject}-h{h}",
                    source_kind="research_device",
                    source_id="synthetic-device",
                    device_model=None,
                    metric="heart_rate",
                    value=value,
                    unit="bpm",
                    start_utc=start,
                    end_utc=end,
                    available_at_utc=end,
                    availability="observed",
                    availability_rule=None,
                    tz_name="UTC",
                    utc_offset_minutes=0,
                    tz_provenance="dataset_documentation",
                )
            )
            if h >= 0:
                targets.append(
                    Aggregate(
                        dataset_id="synthetic-cohort",
                        subject_id=subject,
                        metric="heart_rate",
                        unit="bpm",
                        resolution="hour",
                        interval_start_utc=start,
                        interval_end_utc=start + hour,
                        local_date=None,
                        tz_name="UTC",
                        aggregation="mean",
                        value=value,
                        null_reason=None,
                        observed_count=1,
                        coverage=0.25,
                        source_ids=["synthetic-device"],
                        pipeline_version="synthetic-1",
                    )
                )
    now = datetime.now(UTC)
    split = SplitManifest(
        schema_version="0.1",
        manifest_id="synthetic-split",
        created_at_utc=now,
        dataset_snapshot=DatasetSnapshotRef(
            dataset_id="synthetic-cohort",
            dataset_version="synthetic-1",
            snapshot_sha256=document_sha256({"observations": observations, "targets": targets}),
        ),
        task="physiology_forecast",
        fold=None,
        n_folds=None,
        **partition_participants(subjects, seed=42, validation_count=2, test_count=2),
        lookback_hours=4,
        horizon_hours=2,
        embargo_hours=0,
        cutoff_stride_hours=1,
        min_history_hours=2,
        evaluation_window=TimeWindow(start_utc=base, end_utc=base + 4 * hour),
        seed=42,
        test_opened_at_utc=None,
    )
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True))
    environment_hash = hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest()

    def run_manifest(model_id: str) -> RunManifest:
        return RunManifest(
            schema_version="0.1",
            run_id=model_id,
            created_at_utc=now,
            git_sha=git_sha,
            git_dirty=dirty,
            config_sha256=document_sha256(config),
            dataset_snapshot=split.dataset_snapshot,
            split_manifest_sha256=document_sha256(split),
            task=split.task,
            feature_order=["heart_rate"],
            model=ModelRef(
                model_id=model_id, checkpoint_source=None, checkpoint_revision=None, license=None
            ),
            environment_sha256=environment_hash,
            seed=split.seed,
            artifact=None,
            metrics_paths=["evaluation.json"],
        )

    if args.paired:
        comparison = compare_forecasts(
            split,
            observations,
            targets,
            _last_value,
            _linear_prefix,
            baseline_config=config,
            candidate_config=config,
        )
        hashes = write_comparison_packet(
            args.output,
            split,
            run_manifest("synthetic-last-value"),
            run_manifest("synthetic-linear-prefix"),
            comparison,
        )
        counts = comparison.summary.counts
    else:
        result = evaluate_forecast(split, observations, targets, _last_value, config)
        hashes = write_packet(args.output, split, run_manifest("synthetic-last-value"), result)
        counts = result.counts
    print(
        json.dumps(
            {
                "data_mode": "synthetic",
                "issue_7_real_cohort_gate": "pending PMData",
                "python": platform.python_version(),
                "git_sha": git_sha,
                "git_dirty": dirty,
                "output": str(args.output.resolve()),
                "counts": counts,
                "split_sha256": document_sha256(split),
                "packet_hashes": hashes,
            },
            sort_keys=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
