"""Reproduce descriptive paired evidence from original private development packets."""

import argparse
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from importlib.metadata import version
from pathlib import Path

from pydantic import TypeAdapter

from hachi.contracts.base import GitSha
from hachi.contracts.manifests import SplitManifest
from hachi.evaluation.clinical_protocol import ClinicalProtocol, clinical_fold_plan
from hachi.evaluation.serialization import document_bytes, document_sha256

from .data import at_risk_windows
from .encoder_features import EncoderReturnPins, load_encoder_features
from .evidence import FAMILIES, input_hashes, packet_scores, replay, validate_predictions
from .metrics import Score
from .pretrained_comparison import compare
from .pretrained_features import build_meanpool_features, load_chronos_features, sha
from .pretrained_protocol import REPO, load_pretrained_protocol
from .protocol import load_protocol
from .run import clinical_split

# A new publisher expands the owned source inventory. Verify older heads in their
# original implementation, never by weakening artifact source guards or refitting.
ARCHIVED_WORKER = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from hachi.models.illness.pretrained_evidence import compile_report
args = json.loads(sys.argv[2])
try:
    result = compile_report(**{k: Path(v) if v is not None else None for k,v in args.items()})
    print(json.dumps(result, sort_keys=True, allow_nan=False))
except Exception:
    sys.exit(1)
"""


def archived_report(snapshot, packet, root, chronos, encoder_return, encoder_pins) -> dict:
    summary = json.loads((root / "summary.json").read_bytes())
    commit = TypeAdapter(GitSha).validate_python(summary["git_sha"])
    resolved = subprocess.check_output(
        ["git", "rev-parse", f"{commit}^{{commit}}"], cwd=REPO, text=True
    ).strip()
    if resolved != commit:
        raise ValueError("scoring revision must be an exact retained commit")
    payload = subprocess.check_output(
        ["git", "archive", commit, "src", "configs", "infra", "uv.lock"], cwd=REPO
    )
    arguments = {
        "snapshot": str(snapshot.absolute()),
        "packet": str(packet.absolute()),
        "run": str(root.absolute()),
        "inference": str(chronos.absolute()),
        "encoder_return": str(encoder_return.absolute()),
        "encoder_pins": str(encoder_pins.absolute()),
    }
    # Fresh extraction avoids trusting a pre-existing writable cache. Git discovery
    # remains in this checkout; -I prevents ambient modules mixing with archived ones.
    with tempfile.TemporaryDirectory(prefix="comparison-source-", dir=REPO / ".cache") as tmp:
        with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
            archive.extractall(tmp, filter="data")
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                ARCHIVED_WORKER,
                str(Path(tmp) / "src"),
                json.dumps(arguments),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode:
        raise ValueError("original frozen-feature packet failed archived verification")
    try:
        verified = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ValueError("archived verification returned invalid aggregate evidence") from None
    if not isinstance(verified, dict) or verified.get("scoring_commit") != commit:
        raise ValueError("archived verification differs from claimed scoring revision")
    return verified


def accepted_baselines(roots: dict[str, Path], accepted: dict) -> dict:
    if set(roots) != set(FAMILIES):
        raise ValueError("all three accepted original baseline packets are required")
    inventories = {family: input_hashes(root) for family, root in roots.items()}
    for family, actual in inventories.items():
        expected = accepted["report_provenance"]["input_packets"][family]
        if (
            actual != expected["files_sha256"]
            or document_sha256(actual) != expected["inventory_sha256"]
        ):
            raise ValueError("baseline packet differs from accepted immutable inventory")
    return inventories


def immutable_inputs(paths: dict[str, Path]) -> dict[str, str]:
    """Publish only aggregate inventory pins; private relative paths stay local."""
    return {
        role: (
            sha(path)
            if path.is_file()
            else document_sha256(
                {str(p.relative_to(path)): sha(p) for p in sorted(path.rglob("*")) if p.is_file()}
            )
        )
        for role, path in paths.items()
    }


def assemble(
    snapshot, packet, roots, baseline_root, chronos, encoder_return, encoder_pins, base_python
):
    comparison = load_pretrained_protocol(REPO / "configs/experiments/illness/pretrained.json")
    task = load_protocol(REPO / comparison.task_protocol.path)
    clinical = ClinicalProtocol.model_validate_json(
        (REPO / comparison.clinical_protocol.path).read_bytes()
    )
    plan = clinical_fold_plan(snapshot, clinical)
    if set(roots) != {r.name for r in comparison.representations}:
        raise ValueError("all four original frozen-feature packets are required")
    baseline_roots = {f: baseline_root / f"{f}-002" for f in FAMILIES}
    accepted_path = REPO / "reports/models/illness/phase1.json"
    immutable_paths = {
        "accepted_baseline_report": accepted_path,
        "clinical_snapshot": snapshot,
        "context_packet": packet,
        "chronos_return": chronos,
        "encoder_return": encoder_return,
        "encoder_pins": encoder_pins,
    }
    captured_inputs = immutable_inputs(immutable_paths)
    accepted = json.loads(accepted_path.read_bytes())
    inventories = accepted_baselines(baseline_roots, accepted)
    frozen_inventories = {name: input_hashes(root) for name, root in roots.items()}
    baseline_commits = set()
    for family, root in baseline_roots.items():
        summary = json.loads((root / "summary.json").read_bytes())
        # The accepted JSON omits learned thresholds and attaches aggregate audits;
        # the exact original private inventory above binds those original bytes.
        if (
            summary["protocol_sha256"] != task.sha256
            or summary["shared_protocol_sha256"] != document_sha256(clinical)
            or summary["fold_plan_sha256"] != document_sha256(plan)
            or any(
                summary[k] != accepted["families"][family][k]
                for k in (
                    "git_sha",
                    "protocol_sha256",
                    "shared_protocol_sha256",
                    "fold_plan_sha256",
                    "reports",
                )
            )
        ):
            raise ValueError("accepted baselines differ from current frozen identities")
        baseline_commits.add(TypeAdapter(GitSha).validate_python(summary["git_sha"]))
        validate_predictions(snapshot, root, plan, task)
        for fold in plan.folds:
            if fold.outer_fold != 0:
                continue
            for h in task.horizons_hours:
                for candidate in task.candidate_order:
                    split = SplitManifest.model_validate_json(
                        (root / f"inner-{fold.inner_fold}-{h}h-{candidate}/split.json").read_bytes()
                    )
                    if split != clinical_split(snapshot, fold, task, clinical, h):
                        raise ValueError("baseline differs from complete frozen split")
    if len(baseline_commits) != 1:
        raise ValueError("accepted baseline scoring revisions differ")
    baseline_replay = replay(
        list(baseline_roots.values()), next(iter(baseline_commits)), base_python
    )
    verified = {
        name: archived_report(snapshot, packet, root, chronos, encoder_return, encoder_pins)
        for name, root in roots.items()
    }
    features = load_encoder_features(
        snapshot,
        packet,
        encoder_return,
        comparison,
        EncoderReturnPins.model_validate_json(encoder_pins.read_bytes()),
    )
    features["meanpool_hr"] = build_meanpool_features(snapshot, packet, comparison)
    features["chronos_hr"] = load_chronos_features(snapshot, packet, chronos, comparison)
    for name, receipt in verified.items():
        if (
            receipt["feature_candidate"] != name
            or receipt["comparison_sha256"] != document_sha256(comparison)
            or receipt["task_sha256"] != task.sha256
            or receipt["clinical_sha256"] != document_sha256(clinical)
            or receipt["fold_plan_sha256"] != document_sha256(plan)
            or receipt["feature_provenance"] != features[name].provenance
            or receipt["outer_test"] != "sealed"
            or receipt["serving"] != "unavailable"
        ):
            raise ValueError("archived packet differs from current frozen comparison")
    supported = {
        name: frozenset(
            key
            for fold in plan.folds
            if fold.outer_fold == 0
            for key in feature.supported_by_inner[fold.inner_fold]
            if key[0] in fold.validation_subjects
        )
        for name, feature in features.items()
    }
    development = sorted(
        {s for f in plan.folds if f.outer_fold == 0 for s in f.validation_subjects}
    )
    windows, _ = at_risk_windows(snapshot, development, task)
    views = {}
    for h in task.horizons_hours:
        scores = {
            family: {c: packet_scores(root, h, c) for c in task.candidate_order}
            for family, root in baseline_roots.items()
        }
        for family, root in roots.items():
            scores[family] = {c: [] for c in task.candidate_order}
            for entry in verified[family]["fold_evidence"]:
                if entry["horizon_hours"] == h and entry["status"] == "fitted":
                    path = (
                        root
                        / f"inner-{entry['inner_fold']}-{h}h-{entry['candidate']}/predictions.json"
                    )
                    scores[family][entry["candidate"]].extend(
                        TypeAdapter(list[Score]).validate_json(path.read_bytes())
                    )
        views[str(h)] = compare(
            scores, supported, [w for w in windows if w.horizon_hours == h], task, comparison
        )
    if (
        accepted_baselines(baseline_roots, accepted) != inventories
        or any(input_hashes(roots[name]) != value for name, value in frozen_inventories.items())
        or immutable_inputs(immutable_paths) != captured_inputs
    ):
        raise ValueError("private evidence changed during comparison")
    return {
        "producing_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "comparison_sha256": document_sha256(comparison),
        "task_sha256": task.sha256,
        "clinical_sha256": document_sha256(clinical),
        "fold_plan_sha256": document_sha256(plan),
        "accepted_baseline_report_sha256": captured_inputs["accepted_baseline_report"],
        "original_inputs_sha256": captured_inputs,
        "baseline_input_inventories_sha256": {
            k: document_sha256(v) for k, v in inventories.items()
        },
        "frozen_input_inventories_sha256": {
            k: document_sha256(v) for k, v in frozen_inventories.items()
        },
        "baseline_base_replay": baseline_replay,
        "frozen_admission": verified,
        "metric_environment": {
            name: version(name) for name in ("numpy", "scikit-learn", "pyarrow", "pydantic")
        },
        "views": views,
        "scope": "phase1-selected-retrospective-cohort-development-only",
        "selection": "descriptive_only_no_final_winner",
        "population_calibration": "unsupported_selected_survey_cohort",
        "outer_test": "sealed",
        "serving": "unavailable",
        "issue_completion": "incomplete",
    }


def render(report: dict) -> str:
    report = json.loads(document_bytes(report))
    lines = [
        "# Frozen clinical feature comparison",
        "",
        f"Producing commit: `{report['producing_commit']}`. "
        f"Comparison: `{report['comparison_sha256']}`.",
        "",
        "All seven families use original untouched inner-validation packets. "
        "Whole-window views expose unavailable folds; the common context requires all four "
        "original runtime support flags. Paired differences use identical rows and "
        "whole-participant uncertainty. No model is selected or served; the outer test "
        "remains sealed and #13 remains incomplete.",
        "",
        "| Horizon | Family | Head | Eligible | Scored | AUPRC | Brier | Coverage |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for horizon, views in report["views"].items():
        for family, heads in views["whole_window"].items():
            for head, view in heads.items():
                m = view["report"]["metrics"]

                def number(value):
                    return "unavailable" if value is None else f"{value:.6g}"

                lines.append(
                    f"| {horizon}h | {family} | {head} | {view['eligible_windows']} | "
                    f"{view['scored_windows']} | {number(m['auprc'])} | {number(m['brier'])} | "
                    f"{view['coverage_status']} |"
                )
    lines += [
        "",
        "The JSON is authoritative for all ranking/calibration metrics, reliability bins, "
        "event sensitivity, PPV, alert episodes, observed negative-day burden, interval lead "
        "time, paired differences and participant uncertainty. Missing folds are never "
        "filled with negative labels. The frozen training burden cap does not guarantee "
        "untouched validation burden. Survey participation is a strong confound; pretrained "
        "cohort overlap is unknown. These selected-cohort COVID-related labels do not "
        "establish performance for all colds or population calibration.",
        "",
        "The clock is shifted floating local represented as Z, not actual UTC. Adequate "
        "independent negative calibration, complete selection/final held-out evidence "
        "and validated causal serving remain required.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "snapshot",
        "context-packet",
        "baseline-root",
        "chronos-inference",
        "encoder-return",
        "base-python",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument(
        "--run", nargs=2, action="append", metavar=("FAMILY", "PRIVATE_PATH"), required=True
    )
    parser.add_argument(
        "--encoder-pins",
        type=Path,
        default=REPO / "configs/experiments/illness/encoder-return-001.json",
    )
    args = parser.parse_args()
    try:
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True):
            raise ValueError("comparison publisher requires clean committed source")
        if len(dict(args.run)) != len(args.run):
            raise ValueError("duplicate original frozen-feature family")
        result = assemble(
            args.snapshot,
            args.context_packet,
            {name: Path(p) for name, p in args.run},
            args.baseline_root,
            args.chronos_inference,
            args.encoder_return,
            args.encoder_pins,
            args.base_python,
        )
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "comparison.json").write_bytes(document_bytes(result))
        (args.output / "comparison.md").write_text(render(result))
        print(
            json.dumps(
                {
                    "horizons": list(result["views"]),
                    "families": 7,
                    "outer_test": "sealed",
                    "serving": "unavailable",
                }
            )
        )
        return 0
    except (ValueError, OSError, KeyError, subprocess.SubprocessError):
        print(
            "Comparison evidence failed validation or I/O; private rows withheld.", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
