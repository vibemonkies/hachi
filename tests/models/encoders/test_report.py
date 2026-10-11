import hashlib
import json

import pytest

np = pytest.importorskip("numpy", reason="the encoder report requires the optional baselines extra")

from hachi.models.encoders.report import TREE, embedding_drift, per_fold, tree_crosscheck  # noqa: E402


def _packet(run, fold, name, deltas):
    root = run / fold / f"{name}-vs-ridge-handcrafted"
    (root / "candidate").mkdir(parents=True)
    summary = {
        "difference": {
            "mae": {"value": sum(deltas) / len(deltas)},
            "subjects": [{"mae": d} for d in deltas],
        }
    }
    (root / "comparison.json").write_text(json.dumps(summary))
    for file in ("split.json", "origins.json", "evaluation.json"):
        (root / "candidate" / file).write_text(f"{fold}:{file}")
    return root


def test_tree_crosscheck_reads_the_nested_published_index(tmp_path):
    _packet(tmp_path, "outer-0-inner-0", TREE, [0.5])
    digest = {
        f: hashlib.sha256(f"outer-0-inner-0:{f}".encode()).hexdigest()
        for f in ("split.json", "origins.json", "evaluation.json")
    }
    index = {
        "protocol_sha256": "p",
        "nested_plan_sha256": "n",
        "packets": {
            "outer-0-inner-0": {"evaluations": {TREE: {**digest, "evaluation.json": "0" * 64}}}
        },
    }
    check = tree_crosscheck(tmp_path, index)
    assert check["checked"] == 3 and check["matched"] == 2
    assert check["mismatched"] == [f"outer-0-inner-0/evaluations/{TREE}/evaluation.json"]


def test_per_fold_and_drift_report_only_aggregates(tmp_path):
    _packet(tmp_path, "outer-0-inner-0", "cand", [-1.0, 2.0])
    _packet(tmp_path, "outer-0-inner-1", "cand", [0.5, 0.5])
    folds = per_fold(tmp_path)["cand"]
    assert folds["fold_delta_mae"] == [0.5, 0.5]
    assert folds["participants_lower_higher"] == [1, 3]
    assert folds["participant_delta_mae_min_median_max"] == [-1.0, 0.5, 2.0]
    rng = np.random.default_rng(0)
    full = rng.normal(size=(8, 4))
    np.savez(tmp_path / "wbm.npz", wbm_full=full, wbm_same=full, wbm_flip=-full)
    drift = embedding_drift(tmp_path / "wbm.npz")
    assert drift["wbm_same"]["cosine_mean"] == pytest.approx(1.0)
    assert drift["wbm_flip"]["cosine_mean"] == pytest.approx(-1.0)
