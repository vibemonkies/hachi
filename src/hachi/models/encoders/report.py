"""Sanitized aggregate report for #11 from a private run, its embeddings and the GX10 evidence.

  python -m hachi.models.encoders.report --run PRIVATE_RUN --inputs-audit JSON \
      --embeddings wbm.npz --evidence infra/gx10/encoders/evidence/DATE \
      --packet-index reports/evaluation/pmdata-hourly-validation/packet-index.json --output JSON

The output holds counts, metrics, hashes and distribution summaries only: no participant ids,
rows, cutoffs or predictions.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from statistics import median

import numpy as np

TREE = "causal-hourly-tree-v1"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_crosscheck(run: Path, index: dict) -> dict[str, object]:
    """Our tree packets against the independently published #9 packet index, byte for byte."""
    published: dict[str, str] = {}

    def flatten(node: object, prefix: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                flatten(value, f"{prefix}/{key}" if prefix else key)
        else:
            published[prefix] = node

    flatten(index["packets"], "")
    checked, matched, mismatched = 0, 0, []
    for fold in sorted(p for p in run.iterdir() if p.name.startswith("outer-")):
        packet = fold / f"{TREE}-vs-ridge-handcrafted" / "candidate"
        for name in ("split.json", "origins.json", "evaluation.json"):
            key = f"{fold.name}/evaluations/{TREE}/{name}"
            if key not in published:
                continue
            checked += 1
            if _sha(packet / name) == published[key]:
                matched += 1
            else:
                mismatched.append(key)
    return {
        "checked": checked,
        "matched": matched,
        "mismatched": mismatched,
        "published_protocol_sha256": index["protocol_sha256"],
        "published_nested_plan_sha256": index["nested_plan_sha256"],
    }


def per_fold(run: Path) -> dict[str, dict[str, object]]:
    """Per-model fold-level paired ΔMAE and the sign split across participants."""
    out: dict[str, dict[str, object]] = {}
    for fold in sorted(p for p in run.iterdir() if p.name.startswith("outer-")):
        for packet in sorted(fold.glob("*-vs-ridge-handcrafted")):
            name = packet.name.removesuffix("-vs-ridge-handcrafted")
            summary = json.loads((packet / "comparison.json").read_bytes())
            subjects = summary["difference"]["subjects"]
            entry = out.setdefault(name, {"fold_delta_mae": [], "deltas": []})
            mae = summary["difference"]["mae"]
            entry["fold_delta_mae"].append(None if mae is None else round(mae["value"], 3))
            entry["deltas"] += [s["mae"] for s in subjects]
    for entry in out.values():
        deltas = entry.pop("deltas")
        entry["participants_lower_higher"] = [
            sum(d < 0 for d in deltas),
            sum(d > 0 for d in deltas),
        ]
        entry["participant_delta_mae_min_median_max"] = [
            round(min(deltas), 3),
            round(median(deltas), 3),
            round(max(deltas), 3),
        ]
    return out


def embedding_drift(path: Path) -> dict[str, object]:
    """How far each WBM input ablation moves the frozen embedding of the same window."""
    with np.load(path, allow_pickle=False) as data:
        full = data["wbm_full"].astype(np.float64)
        out = {}
        for name in sorted(k for k in data.files if k.startswith("wbm_") and k != "wbm_full"):
            other = data[name].astype(np.float64)
            cos = (full * other).sum(1) / (
                np.linalg.norm(full, axis=1) * np.linalg.norm(other, axis=1)
            )
            rel = np.linalg.norm(full - other, axis=1) / np.linalg.norm(full, axis=1)
            out[name] = {
                "cosine_mean": float(cos.mean()),
                "cosine_p05": float(np.quantile(cos, 0.05)),
                "relative_l2_mean": float(rel.mean()),
            }
        spread = np.linalg.norm(full - full.mean(0), axis=1) / np.linalg.norm(full, axis=1)
        out["between_window_relative_spread_mean"] = float(spread.mean())
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--inputs-audit", required=True, type=Path)
    parser.add_argument("--embeddings", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--packet-index", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    summary = json.loads((args.run / "aggregate-summary.json").read_bytes())
    audit = json.loads(args.inputs_audit.read_bytes())
    evidence = {p.name: json.loads(p.read_bytes()) for p in sorted(args.evidence.glob("*.json"))}
    report = {
        "issue": 11,
        "data_mode": summary["data_mode"],
        "dataset_snapshot": summary["dataset_snapshot"],
        "protocol_sha256": summary["protocol_sha256"],
        "experiment_sha256": summary["experiment_sha256"],
        "nested_plan_sha256": summary["nested_plan_sha256"],
        "git_sha": summary["git_sha"],
        "git_dirty": summary["git_dirty"],
        "environment_sha256": summary["environment_sha256"],
        "outer_test_sealed": summary["outer_test_sealed"],
        "active_outer_fold": summary["active_outer_fold"],
        "inner_folds": summary["inner_folds"],
        "validation_participants": summary["validation_participants"],
        "baseline": summary["baseline"],
        "paired_definition": summary["paired_definition"],
        "models": summary["models"],
        "paired_vs_baseline": summary["paired_vs_baseline"],
        "per_fold": per_fold(args.run),
        "tree_crosscheck": tree_crosscheck(args.run, json.loads(args.packet_index.read_bytes())),
        "inputs": {k: v for k, v in audit.items() if k != "window"},
        "window": audit["window"],
        "embedding_tables": summary["tables"],
        "embedding_drift": embedding_drift(args.embeddings),
        "evidence_files": sorted(evidence),
        "resources": summary["resources"],
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"written": str(args.output)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
