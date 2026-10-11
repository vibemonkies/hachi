"""Four generated-only model runs with immutable-artifact inference replay."""

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

from hachi.contracts.base import Contract, DatasetSnapshotRef
from hachi.contracts.manifests import ModelRef, RunManifest, SplitManifest, TimeWindow
from hachi.contracts.tables import Aggregate, Observation
from hachi.evaluation import (
    EvaluationConfig,
    TrainingPrefix,
    evaluate_forecast,
    partition_participants,
)
from hachi.evaluation.artifacts import write_packet
from hachi.evaluation.serialization import document_sha256

from .artifacts import load_artifact, save_artifact, source_hashes
from .forecast import BaselineConfig, fit_baseline
from .tree import FEATURES, TreeConfig, fit_tree


class DemoConfig(Contract):
    baselines: list[BaselineConfig]
    tree: TreeConfig
    evaluation: EvaluationConfig


def main() -> None:
    import numpy
    import scipy
    import sklearn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="new private run directory")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    config = DemoConfig.model_validate_json(
        (root / "configs/models/baselines/synthetic-hourly.json").read_bytes()
    )
    if config.evaluation.data_mode != "synthetic":
        parser.error("this command generates synthetic data only")
    methods = [c.method for c in config.baselines]
    if (
        set(methods) != {"last_valid", "seasonal_naive", "train_population_mean"}
        or len(methods) != 3
    ):
        parser.error("configure exactly the three simple comparators")
    if any(
        c.metric != "heart_rate" or c.aggregation != "mean"
        for c in [*config.baselines, config.tree]
    ):
        parser.error("this generated cohort uses heart-rate means")
    if config.evaluation.metric != "heart_rate" or config.evaluation.aggregation != "mean":
        parser.error("evaluation must match the generated heart-rate target")
    base = datetime(2026, 10, 10, tzinfo=UTC)
    hour = timedelta(hours=1)
    subjects = [f"generated-{i}" for i in range(8)]
    observations: list[Observation] = []
    targets: list[Aggregate] = []
    for index, subject in enumerate(subjects):
        for h in range(-96, 8):
            start = base + h * hour
            value = 65.0 + index + 5 * math.sin(start.hour * 2 * math.pi / 24)
            observations.append(
                Observation(
                    dataset_id="generated-baselines",
                    subject_id=subject,
                    record_id=f"{subject}-{h}",
                    source_kind="research_device",
                    source_id="generated",
                    device_model=None,
                    metric="heart_rate",
                    unit="bpm",
                    value=value,
                    start_utc=start,
                    end_utc=start + timedelta(minutes=15),
                    available_at_utc=start + timedelta(minutes=15),
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
                        dataset_id="generated-baselines",
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
                        source_ids=["generated"],
                        pipeline_version="generated-1",
                    )
                )
    now = datetime.now(UTC)
    snapshot = DatasetSnapshotRef(
        dataset_id="generated-baselines",
        dataset_version="generated-1",
        snapshot_sha256=document_sha256({"observations": observations, "targets": targets}),
    )
    split = SplitManifest(
        schema_version="0.1",
        manifest_id="generated-baseline-split",
        created_at_utc=now,
        dataset_snapshot=snapshot,
        task="physiology_forecast",
        fold=None,
        n_folds=None,
        **partition_participants(subjects, seed=config.tree.seed, validation_count=2, test_count=2),
        lookback_hours=48,
        horizon_hours=2,
        embargo_hours=0,
        cutoff_stride_hours=2,
        min_history_hours=24,
        evaluation_window=TimeWindow(start_utc=base, end_utc=base + 8 * hour),
        seed=config.tree.seed,
        test_opened_at_utc=None,
    )
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True))
    environment = hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    receipt = {
        "data_mode": "synthetic",
        "git_sha": git_sha,
        "git_dirty": dirty,
        "python": platform.python_version(),
        "sklearn": sklearn.__version__,
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
        "environment_sha256": environment,
        "source_sha256": source_hashes(),
        "split_sha256": document_sha256(split),
        "real_cohort_gate": "pending admitted PMData and frozen real protocol",
        "models": {},
    }
    for model_config in [*config.baselines, config.tree]:
        fitted = []

        def factory(training: TrainingPrefix, model_config=model_config, fitted=fitted):
            model = (
                fit_tree(training, model_config)
                if isinstance(model_config, TreeConfig)
                else fit_baseline(training, model_config)
            )
            fitted.append(model)
            return model.predict

        started = perf_counter()
        result = evaluate_forecast(split, observations, targets, factory, config.evaluation)
        elapsed = perf_counter() - started
        model = fitted[0]
        identity = document_sha256({"model": model, "sources": source_hashes()})[:16]
        artifact_id = f"{model.model_id}-{identity}"
        output = args.output / "models" / artifact_id
        reference = save_artifact(output, model, artifact_id=artifact_id)
        loaded = load_artifact(output, reference)
        replay = evaluate_forecast(
            split, observations, targets, lambda _, loaded=loaded: loaded.predict, config.evaluation
        )
        if replay.predictions != result.predictions or replay.counts != result.counts:
            raise RuntimeError("saved artifact replay changed predictions or coverage")
        run = RunManifest(
            schema_version="0.1",
            run_id=model.model_id,
            created_at_utc=now,
            git_sha=git_sha,
            git_dirty=dirty,
            config_sha256=document_sha256(config.evaluation),
            dataset_snapshot=snapshot,
            split_manifest_sha256=document_sha256(split),
            task="physiology_forecast",
            feature_order=list(FEATURES)
            if isinstance(model_config, TreeConfig)
            else ["heart_rate"],
            model=ModelRef(
                model_id=model.model_id,
                checkpoint_source=None,
                checkpoint_revision=None,
                license=None,
            ),
            environment_sha256=environment,
            seed=config.tree.seed,
            artifact=reference,
            metrics_paths=["evaluation.json"],
        )
        hashes = write_packet(args.output / "evaluations" / model.model_id, split, run, result)
        receipt["models"][model.model_id] = {
            "artifact": reference.model_dump(),
            "artifact_replay_verified": True,
            "elapsed_seconds": elapsed,
            "counts": result.counts,
            "metrics": {
                name: asdict(value) if value is not None else None
                for name in ("mae", "rmse", "median_pinball_loss")
                if (value := getattr(result.metrics, name)) is not None
            },
            "packet_sha256": hashes,
        }
    data = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(
        args.output / "synthetic-summary.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    print(data.decode())


if __name__ == "__main__":
    main()
