"""Private PMData validation of frozen-embedding heads against the same head on handcrafted inputs.

  python -m hachi.models.encoders.run --snapshot DIR --experiment JSON --inputs inputs.npz \
      --embeddings wbm.npz --embeddings moment.npz --output PRIVATE_DIR

Uses the shared #7/#9 protocol unchanged (``load_inputs``/``fold_split``): only the inner
validation folds of the active outer fold are scored, and its outer test stays sealed. Every
candidate is paired with the handcrafted ridge head on identical origins; the #9 tree is paired
too, as the canonical comparator. Packets, head artifacts and out-of-fold predictions stay in
the private output; ``aggregate-summary.json`` holds aggregates only.
"""

import argparse
import hashlib
import json
import os
import platform
import resource
import subprocess
import sys
import traceback
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from hachi.contracts.base import ArtifactRef
from hachi.contracts.manifests import ModelRef, RunManifest
from hachi.evaluation import compare_forecasts, evaluate_forecast, write_comparison_packet
from hachi.evaluation.forecast import target_quality_eligible
from hachi.evaluation.metrics import bootstrap_participant_mean, combine_metric_reports
from hachi.evaluation.pmdata_run import PMDataProtocol, fold_split, load_inputs
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.baselines import fit_tree
from hachi.models.baselines.tree import FEATURES

from .config import Candidate, EncoderExperiment
from .head import HANDCRAFTED, EmbeddingTable, RidgeHeadArtifact, TrainingPairs, ridge_head_factory

TREE = "causal-hourly-tree-v1"
CHECKPOINTS = {
    "wbm": (
        "MyHeartCounts/openmhc-wbm-dp",
        "5db7e4598e1d1da3cdaeb04dce5e9b1ccaf21334",
        "CC-BY-4.0",
    ),
    "moment": ("AutonLab/MOMENT-1-large", "ca58581bc7bea2ebed4e80dc0a3e4b8b609c6ecc", "MIT"),
}


def source_hashes() -> dict[str, str]:
    package = Path(__file__).resolve().parents[2]
    files = [
        *sorted(Path(__file__).parent.glob("*.py")),
        package / "models/baselines/tree.py",
        package / "models/baselines/forecast.py",
        package / "evaluation/features.py",
        package / "evaluation/serialization.py",
        package / "contracts/causality.py",
    ]
    return {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def load_tables(inputs: Path, embeddings: list[Path]) -> dict[str, EmbeddingTable]:
    """Embedding tables keyed exactly like the inputs they were computed from."""
    with np.load(inputs, allow_pickle=False) as data:
        keys = (data["subject_ids"], data["as_of_utc"])
        arrays = {"meanpool": data["meanpool"]}
    for path in embeddings:
        with np.load(path, allow_pickle=False) as data:
            if not (
                np.array_equal(data["subject_ids"], keys[0])
                and np.array_equal(data["as_of_utc"], keys[1])
            ):
                raise ValueError(f"{path.name} rows do not match the inputs they claim")
            for name in data.files:
                if name.startswith("wbm_"):
                    arrays[name] = data[name]
            if "moment" in data.files:
                arrays["moment"] = data["moment"]
                arrays["moment_hr_only"] = data["moment"][:, : data["moment"].shape[1] // 5]
    subjects = [str(s) for s in keys[0]]
    as_of = [datetime.fromisoformat(str(a)).astimezone(UTC) for a in keys[1]]
    return {
        name: EmbeddingTable.from_arrays(name, subjects, as_of, v) for name, v in arrays.items()
    }


def _write_private(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)


def save_head(output: Path, artifact: RidgeHeadArtifact) -> ArtifactRef:
    model = document_bytes(artifact)
    sources = document_bytes(source_hashes())
    receipt = {
        "artifact_id": output.name,
        "files": {
            "model.json": hashlib.sha256(model).hexdigest(),
            "source-sha256.json": hashlib.sha256(sources).hexdigest(),
        },
    }
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    _write_private(output / "model.json", model)
    _write_private(output / "source-sha256.json", sources)
    _write_private(output / "artifact.json", document_bytes(receipt))
    return ArtifactRef(artifact_id=output.name, artifact_sha256=document_sha256(receipt))


def load_head(path: Path, expected: ArtifactRef) -> RidgeHeadArtifact:
    receipt = json.loads((path / "artifact.json").read_bytes())
    if (
        receipt["artifact_id"] != expected.artifact_id
        or document_sha256(receipt) != expected.artifact_sha256
    ):
        raise ValueError("head receipt does not match the expected immutable reference")
    for name, digest in receipt["files"].items():
        if hashlib.sha256((path / name).read_bytes()).hexdigest() != digest:
            raise ValueError("head content checksum mismatch")
    if json.loads((path / "source-sha256.json").read_bytes()) != source_hashes():
        raise ValueError("head requires its identified implementation")
    return RidgeHeadArtifact.model_validate_json((path / "model.json").read_bytes())


def export_head(root, artifact, tables, split, view, labels, evaluation) -> ArtifactRef:
    """Save a fitted head once, reload it and prove the saved copy replays the same predictions."""
    path = root / f"{artifact.model_id}-{document_sha256(artifact)[:16]}"
    if path.exists():
        receipt = json.loads((path / "artifact.json").read_bytes())
        return ArtifactRef(artifact_id=path.name, artifact_sha256=document_sha256(receipt))
    root.mkdir(mode=0o700, exist_ok=True)
    reference = save_head(path, artifact)
    loaded = load_head(path, reference)
    replay = evaluate_forecast(
        split, view.features, labels, lambda _: loaded.predictor(tables), evaluation.config
    )
    if replay.predictions != evaluation.predictions or replay.counts != evaluation.counts:
        raise RuntimeError("saved head replay changed predictions or inclusion counts")
    return reference


def _model_ref(candidate: Candidate | None) -> ModelRef:
    if candidate is None:
        return ModelRef(
            model_id=TREE, checkpoint_source=None, checkpoint_revision=None, license=None
        )
    encoders = sorted({b.split("_")[0] for b in candidate.blocks if b.split("_")[0] in CHECKPOINTS})
    if len(encoders) == 1:
        source, revision, license_ = CHECKPOINTS[encoders[0]]
        return ModelRef(
            model_id=candidate.name,
            checkpoint_source=source,
            checkpoint_revision=revision,
            license=license_,
        )
    return ModelRef(
        model_id=candidate.name, checkpoint_source=None, checkpoint_revision=None, license=None
    )


def _feature_order(blocks: tuple[str, ...]) -> list[str]:
    order: list[str] = []
    for block in blocks:
        order += list(FEATURES) if block == HANDCRAFTED else [f"{block}:pca"]
    return order


def _metrics(report) -> dict[str, object]:
    return {
        name: asdict(value) if value is not None else None
        for name in ("mae", "rmse", "median_pinball_loss")
        if (value := getattr(report, name)) is not None
    }


def run(
    snapshot: Path,
    experiment: EncoderExperiment,
    inputs: Path,
    embeddings: list[Path],
    output: Path,
) -> dict[str, object]:
    started = perf_counter()
    protocol = PMDataProtocol.model_validate_json(experiment.protocol.resolve().read_bytes())
    plan, view, labels = load_inputs(snapshot, protocol)
    tables = load_tables(inputs, embeddings)
    missing = set(experiment.tables) - set(tables)
    if missing:
        raise ValueError(f"embedding tables not supplied: {sorted(missing)}")
    support = experiment.tables
    selected = [f for f in plan.folds if f.outer_fold == protocol.active_outer_fold]
    repo = Path(__file__).resolve().parents[4]
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True))
    environment = hashlib.sha256((repo / "uv.lock").read_bytes()).hexdigest()
    now = datetime.now(UTC)
    by_name = {c.name: c for c in experiment.candidates}
    baseline = by_name[experiment.baseline]
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    _write_private(output / "experiment.json", document_bytes(experiment))
    _write_private(output / "protocol.json", document_bytes(protocol))
    _write_private(output / "fold-plan.json", document_bytes(plan))
    _write_private(
        output / "tables.json",
        document_bytes(
            {
                n: {"sha256": t.sha256, "rows": len(t.subject_ids), "dim": int(t.vectors.shape[1])}
                for n, t in tables.items()
            }
        ),
    )
    reports: dict[str, list] = defaultdict(list)
    differences: dict[str, list] = defaultdict(list)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    artifacts: dict[str, list] = defaultdict(list)
    oof: list[dict[str, object]] = []
    try:
        for fold in selected:
            split = fold_split(protocol, fold)
            fold_root = output / f"outer-{fold.outer_fold}-inner-{fold.inner_fold}"
            fold_root.mkdir(mode=0o700)
            pairs_cache: dict[str, TrainingPairs] = {}

            def head(candidate: Candidate, fitted: list, pairs_cache=pairs_cache) -> object:
                return ridge_head_factory(
                    experiment.head_for(candidate),
                    model_id=candidate.name,
                    blocks=candidate.blocks,
                    support=support,
                    tables=tables,
                    pairs_cache=pairs_cache,
                    fitted=fitted,
                )

            def config(candidate: Candidate | None):
                # Non-pretrained models keep the protocol's config byte for byte, so the tree
                # packets can be checked against the published #9 packet index.
                if candidate is None or candidate.pretrained_cohort_overlap == "not_applicable":
                    return protocol.evaluation
                overlap = candidate.pretrained_cohort_overlap
                return protocol.evaluation.model_copy(
                    update={
                        "pretrained_cohort_overlap": overlap,
                        "overlap_note": experiment.overlap_notes[overlap],
                    }
                )

            contenders: list[Candidate | None] = [
                c for c in experiment.candidates if c is not baseline
            ]
            contenders.append(None)  # the #9 tree on its own handcrafted inputs
            for candidate in contenders:
                base_fitted: list = []
                cand_fitted: list = []
                if candidate is None:
                    tree_models: list = []

                    def tree_fit(training, models=tree_models):
                        model = fit_tree(training, protocol.tree)
                        models.append(model)
                        return model.predict

                    candidate_factory = tree_fit
                    name = TREE
                else:
                    candidate_factory = head(candidate, cand_fitted)
                    name = candidate.name
                result = compare_forecasts(
                    split,
                    view.features,
                    labels,
                    head(baseline, base_fitted),
                    candidate_factory,
                    baseline_config=config(baseline),
                    candidate_config=config(candidate),
                )
                runs = []
                for label, model, fitted, cand in (
                    ("baseline", baseline.name, base_fitted, baseline),
                    ("candidate", name, cand_fitted, candidate),
                ):
                    reference = None
                    if fitted:
                        evaluation = result.baseline if label == "baseline" else result.candidate
                        reference = export_head(
                            fold_root / "models", fitted[0], tables, split, view, labels, evaluation
                        )
                        artifacts[model].append(reference.model_dump())
                    blocks = (HANDCRAFTED,) if cand is None else cand.blocks
                    runs.append(
                        RunManifest(
                            schema_version="0.1",
                            run_id=f"outer{fold.outer_fold}-inner{fold.inner_fold}-{model}"[:128],
                            created_at_utc=now,
                            git_sha=git_sha,
                            git_dirty=dirty,
                            config_sha256=document_sha256(config(cand)),
                            dataset_snapshot=protocol.expected_snapshot,
                            split_manifest_sha256=document_sha256(split),
                            task="physiology_forecast",
                            feature_order=_feature_order(blocks),
                            model=_model_ref(cand),
                            environment_sha256=environment,
                            seed=protocol.folds.seed,
                            artifact=reference,
                            metrics_paths=["evaluation.json"],
                        )
                    )
                write_comparison_packet(
                    fold_root / f"{name}-vs-{baseline.name}", split, runs[0], runs[1], result
                )
                reports[name].append(result.candidate.metrics)
                oof += oof_rows(fold, name, result.candidate, labels, protocol.evaluation)
                if candidate is contenders[0]:
                    reports[baseline.name].append(result.baseline.metrics)
                    oof += oof_rows(
                        fold, baseline.name, result.baseline, labels, protocol.evaluation
                    )
                differences[name] += list(result.summary.difference.subjects)
                for key, value in result.summary.counts.items():
                    counts[name][key] += value
        write_oof(output / "oof-predictions.parquet", oof)
        summary = summarize(
            experiment, protocol, plan, selected, reports, differences, counts, artifacts
        )
        summary.update(
            {
                "git_sha": git_sha,
                "git_dirty": dirty,
                "environment_sha256": environment,
                "python": platform.python_version(),
                "source_sha256": source_hashes(),
                "tables": {
                    n: {"sha256": t.sha256, "dim": int(t.vectors.shape[1])}
                    for n, t in tables.items()
                },
                "resources": {
                    "elapsed_seconds": round(perf_counter() - started, 1),
                    "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                    * (1 if sys.platform == "darwin" else 1024),
                },
            }
        )
        _write_private(output / "aggregate-summary.json", document_bytes(summary))
        hashes = {
            str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.rglob("*"))
            if p.is_file()
        }
        _write_private(output / "sha256.json", document_bytes(hashes))
        return summary
    except Exception:
        _write_private(
            output / "failure.json", document_bytes({"traceback": traceback.format_exc()})
        )
        raise


def oof_rows(fold, model, evaluation, labels, config) -> list[dict[str, object]]:
    """Every prediction the evaluator made, keyed for joining with #12/#13 harness outputs."""
    by_bin = {
        (t.subject_id, t.interval_start_utc): t
        for t in labels
        if t.metric == config.metric
        and t.resolution == "hour"
        and t.aggregation == config.aggregation
    }
    rows = []
    for prediction in evaluation.predictions:
        origin = prediction.origin
        for window, estimate in zip(origin.targets, prediction.estimates, strict=True):
            label = by_bin.get((origin.subject_id, window.start_utc))
            rows.append(
                {
                    "outer_fold": fold.outer_fold,
                    "inner_fold": fold.inner_fold,
                    "subject_id": origin.subject_id,
                    "cutoff_utc": origin.cutoff,
                    "target_start_utc": window.start_utc,
                    "model": model,
                    "median": None if estimate is None else estimate.median,
                    "label": None if label is None else label.value,
                    "label_eligible": label is not None
                    and label.value is not None
                    and target_quality_eligible(label, config),
                }
            )
    return rows


def write_oof(path: Path, rows: list[dict[str, object]]) -> None:
    table = pa.Table.from_pylist(rows)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    _write_private(path, sink.getvalue().to_pybytes())


def summarize(
    experiment, protocol, plan, selected, reports, differences, counts, artifacts
) -> dict[str, object]:
    def paired(rows) -> dict[str, object]:
        out = {}
        for metric in ("mae", "rmse", "median_pinball_loss"):
            estimate = bootstrap_participant_mean(
                [getattr(d, metric) for d in rows],
                samples=protocol.evaluation.bootstrap_samples,
                confidence=protocol.evaluation.confidence,
                seed=protocol.folds.seed,
            )
            out[metric] = asdict(estimate) if estimate is not None else None
        return out

    roles = {c.name: c.role for c in experiment.candidates}
    return {
        "data_mode": "real",
        "dataset_snapshot": protocol.expected_snapshot.model_dump(),
        "protocol_sha256": document_sha256(protocol),
        "experiment_sha256": document_sha256(experiment),
        "nested_plan_sha256": document_sha256(plan),
        "active_outer_fold": protocol.active_outer_fold,
        "outer_test_sealed": True,
        "inner_folds": len(selected),
        "validation_participants": len({s for f in selected for s in f.validation_subjects}),
        "baseline": experiment.baseline,
        "paired_definition": (
            "candidate minus baseline per validation participant, pooled across inner folds; "
            "negative favours the candidate"
        ),
        "models": {
            name: {
                "role": roles.get(name, "reference"),
                "metrics_full_support": _metrics(
                    combine_metric_reports(rows, seed=protocol.folds.seed)
                ),
                "artifacts": len(artifacts.get(name, [])),
            }
            for name, rows in sorted(reports.items())
        },
        "paired_vs_baseline": {
            name: {
                "participants": len(rows),
                "difference": paired(rows),
                "counts": dict(counts[name]),
            }
            for name, rows in sorted(differences.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--experiment", required=True, type=Path)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--embeddings", action="append", default=[], type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        experiment = EncoderExperiment.model_validate_json(args.experiment.read_bytes())
        summary = run(args.snapshot, experiment, args.inputs, args.embeddings, args.output)
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
