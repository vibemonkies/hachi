"""Pair the frozen tree with each CPU comparator on the prespecified PMData validation."""

import argparse
import hashlib
import json
import os
import resource
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from hachi.contracts.manifests import RunManifest
from hachi.evaluation import compare_forecasts, write_comparison_packet
from hachi.evaluation.metrics import bootstrap_participant_mean
from hachi.evaluation.pmdata_run import PMDataProtocol, fold_split, load_inputs
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.baselines import load_artifact


def main():
    started = perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--baseline-run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    protocol = PMDataProtocol.model_validate_json(args.protocol.read_bytes())
    plan, view, labels = load_inputs(args.snapshot, protocol)
    hashes = json.loads((args.baseline_run / "sha256.json").read_bytes())
    if any(
        hashlib.sha256((args.baseline_run / n).read_bytes()).hexdigest() != h
        for n, h in hashes.items()
    ):
        raise ValueError("baseline packet hash mismatch")
    if (
        document_sha256(protocol)
        != json.loads((args.baseline_run / "aggregate-summary.json").read_bytes())[
            "protocol_sha256"
        ]
    ):
        raise ValueError("protocol differs from baseline execution")
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[2]
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True))
    differences = defaultdict(list)
    counts = defaultdict(Counter)
    refs = []
    for fold in plan.folds:
        if fold.outer_fold != protocol.active_outer_fold:
            continue
        name = f"outer-{fold.outer_fold}-inner-{fold.inner_fold}"
        split = fold_split(protocol, fold)
        run_root = args.baseline_run / name
        models = {}
        manifests = {}
        for packet in (run_root / "evaluations").iterdir():
            run = RunManifest.model_validate_json((packet / "run.json").read_bytes())
            if run.split_manifest_sha256 != document_sha256(split):
                raise ValueError("frozen model uses another split")
            model = load_artifact(run_root / "models" / run.artifact.artifact_id, run.artifact)
            models[run.model.model_id] = model
            manifests[run.model.model_id] = run
        candidate_id = "causal-hourly-tree-v1"
        for baseline_id in sorted(set(models) - {candidate_id}):
            baseline, candidate = models[baseline_id], models[candidate_id]
            result = compare_forecasts(
                split,
                view.features,
                labels,
                lambda _, baseline=baseline: baseline.predict,
                lambda _, candidate=candidate: candidate.predict,
                baseline_config=protocol.evaluation,
                candidate_config=protocol.evaluation,
            )
            for model_id, evaluated in [
                (baseline_id, result.baseline),
                (candidate_id, result.candidate),
            ]:
                expected = hashes[f"{name}/evaluations/{model_id}/evaluation.json"]
                if document_sha256(evaluated) != expected:
                    raise ValueError("paired replay differs from frozen baseline result")
            b_run = manifests[baseline_id].model_copy(
                update={
                    "run_id": f"{name}-{baseline_id}-paired",
                    "created_at_utc": datetime.now(UTC),
                    "git_sha": git_sha,
                    "git_dirty": dirty,
                }
            )
            c_run = manifests[candidate_id].model_copy(
                update={
                    "run_id": f"{name}-{candidate_id}-paired",
                    "created_at_utc": datetime.now(UTC),
                    "git_sha": git_sha,
                    "git_dirty": dirty,
                }
            )
            root = args.output / name / baseline_id
            digest = write_comparison_packet(root, split, b_run, c_run, result)
            refs.append(
                {"path": f"{name}/{baseline_id}", "comparison_sha256": digest["comparison.json"]}
            )
            differences[baseline_id].extend(result.summary.difference.subjects)
            counts[baseline_id].update(result.summary.counts)
    summary = {
        "data_mode": "real",
        "git_sha": git_sha,
        "git_dirty": dirty,
        "protocol_sha256": document_sha256(protocol),
        "outer_test_sealed": True,
        "baseline_run_index_sha256": hashlib.sha256(
            (args.baseline_run / "sha256.json").read_bytes()
        ).hexdigest(),
        "candidate": "causal-hourly-tree-v1",
        "definition": "candidate minus baseline, equal participant paired differences",
        "comparisons": {},
        "private_packet_refs": refs,
        "promotion": ("none; paired error is conditional on joint coverage; inner validation only"),
    }
    for name, rows in sorted(differences.items()):
        if len({r.subject_id for r in rows}) != len(rows):
            raise ValueError("paired validation participants must be disjoint")
        summary["comparisons"][name] = {
            "counts": dict(counts[name]),
            "differences": {
                metric: asdict(
                    bootstrap_participant_mean(
                        [getattr(r, metric) for r in rows],
                        samples=protocol.evaluation.bootstrap_samples,
                        confidence=protocol.evaluation.confidence,
                        seed=protocol.folds.seed,
                    )
                )
                for metric in ("mae", "rmse", "median_pinball_loss")
            },
        }
    summary["resources"] = {
        "elapsed_seconds": perf_counter() - started,
        "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        * (1 if sys.platform == "darwin" else 1024),
        "scope": "whole comparison process, including verification and saved-model replay",
    }
    (args.output / "aggregate-summary.json").write_bytes(document_bytes(summary))
    index = {
        str(p.relative_to(args.output)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in args.output.rglob("*")
        if p.is_file()
    }
    (args.output / "sha256.json").write_bytes(document_bytes(index))
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Validation payloads can contain participant data; print only the error class.
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1) from None
