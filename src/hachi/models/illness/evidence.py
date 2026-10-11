"Reproduce sanitized illness reports from hashed private packets; never rescore models."

import argparse
import hashlib
import io
import json
import math
import subprocess
import tarfile
import tempfile
from dataclasses import replace
from pathlib import Path

from pydantic import TypeAdapter

from hachi.data.clinical.snapshot import read_table
from hachi.data.clinical.windows import onset_labels
from hachi.evaluation.clinical_protocol import ClinicalProtocol, clinical_fold_plan
from hachi.evaluation.serialization import document_sha256

from .data import at_risk_windows
from .metrics import Score, paired_auprc
from .metrics import report as metric_report
from .protocol import load_protocol

REPO = Path(__file__).resolve().parents[4]
FAMILIES = ("survey-history", "nightly-rest", "anomaly-derived")


def packet_scores(root: Path, horizon: int, candidate: str) -> list[Score]:
    rows = []
    for inner in range(3):
        packet = root / f"inner-{inner}-{horizon}h-{candidate}" / "predictions.json"
        rows.extend(TypeAdapter(list[Score]).validate_json(packet.read_bytes()))
    return rows


def input_hashes(root: Path) -> dict[str, str]:
    "Relative names contain protocol/fold/model roles, never participant identifiers."
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*.json"))
        if p.is_file()
    }


def validate_predictions(snapshot, root, plan, protocol) -> None:
    """Receipts alone do not prove that a saved scored row belonged to its fold."""
    for fold in plan.folds:
        if fold.outer_fold != protocol.active_outer_fold:
            continue
        expected, _ = at_risk_windows(snapshot, fold.validation_subjects, protocol)
        for horizon in protocol.horizons_hours:
            target = {(w.subject_id, w.cutoff): w for w in expected if w.horizon_hours == horizon}
            for candidate in protocol.candidate_order:
                packet = root / f"inner-{fold.inner_fold}-{horizon}h-{candidate}"
                split = json.loads((packet / "split.json").read_bytes())
                if split["test_opened_at_utc"] is not None or any(
                    tuple(split[key]) != tuple(value) for key, value in fold.partitions().items()
                ):
                    raise ValueError("private packet split differs from sealed clinical fold")
                rows = TypeAdapter(list[Score]).validate_json(
                    (packet / "predictions.json").read_bytes()
                )
                actual = {(s.window.subject_id, s.window.cutoff): s.window for s in rows}
                if len(actual) != len(rows) or set(actual) != set(target):
                    raise ValueError("scored rows differ from eligible validation cohort")
                for score in rows:
                    window = score.window
                    if not math.isfinite(score.probability) or not 0 <= score.probability <= 1:
                        raise ValueError("invalid saved probability")
                    if (
                        replace(window, features=window.features[:4])
                        != target[(window.subject_id, window.cutoff)]
                    ):
                        raise ValueError("saved targets or survey predictors differ from snapshot")


def label_grid_check(snapshot: Path, clinical: ClinicalProtocol) -> dict:
    plan = clinical_fold_plan(snapshot, clinical)
    active = [f for f in plan.folds if f.outer_fold == clinical.active_outer_fold]
    development = sorted({s for f in active for s in f.validation_subjects})
    # Both paths are restricted before reading outcome rows; outer test stays sealed.
    actual = read_table(snapshot, "onset_windows", development).to_pylist()
    rebuilt = onset_labels(snapshot, step_hours=24, subjects=development).to_pylist()
    index = {(r["subject_id"], r["cutoff_utc"]): r for r in rebuilt}
    comparisons, mismatches = 0, 0
    for row in actual:
        other = index.pop((row["subject_id"], row["cutoff_utc"]), None)
        for horizon in (24, 48, 72):
            for name in (f"onset_{horizon}h", f"onset_episode_{horizon}h"):
                comparisons += 1
                mismatches += other is None or row[name] != other[name]
    if mismatches or index:
        raise ValueError("recomputed label grid differs from snapshot")
    return {
        "development_cutoffs": len(actual),
        "onset_label_episode_comparisons": comparisons,
        "mismatches": mismatches,
        "outer_test_read": False,
    }


def replay(packets: list[Path], scoring_commit: str, base_python: Path) -> dict:
    "Receipts require their exact source inventory, so additions cannot silently bypass pins."
    payload = subprocess.check_output(["git", "archive", scoring_commit, "src"], cwd=REPO)
    with tempfile.TemporaryDirectory(prefix="hachi-illness-replay-") as temporary:
        with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
            archive.extractall(temporary, filter="data")
        result = subprocess.run(
            [
                # Resolving a venv executable symlink would discard its pyvenv.cfg.
                str(base_python.absolute()),
                "-I",
                str(Path(__file__).with_name("replay.py")),
                "--scoring-source",
                str(Path(temporary) / "src"),
                "--packets",
                *(str(p.resolve()) for p in packets),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise ValueError("base-only replay failed; private worker output withheld")
    return json.loads(result.stdout)


def assemble(
    snapshot: Path,
    roots: dict[str, Path],
    base_python: Path,
    protocol_path: Path,
    clinical_path: Path,
    previous: dict[str, Path] | None = None,
) -> dict:
    if set(roots) != set(FAMILIES):
        raise ValueError("all frozen feature families required")
    protocol = load_protocol(protocol_path)
    clinical = ClinicalProtocol.model_validate_json(clinical_path.read_bytes())
    plan = clinical_fold_plan(snapshot, clinical)
    summaries, identities, provenance = {}, set(), {}
    producer = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    for name in ("evidence.py", "replay.py"):
        relative = f"src/hachi/models/illness/{name}"
        committed = subprocess.check_output(["git", "show", f"{producer}:{relative}"], cwd=REPO)
        if committed != Path(__file__).with_name(name).read_bytes():
            raise ValueError("commit evidence implementation before report generation")
    if subprocess.check_output(
        ["git", "diff", "HEAD", "--name-only", "--", "src/hachi"], cwd=REPO, text=True
    ):
        raise ValueError("tracked report dependencies differ from producing commit")
    for family, root in roots.items():
        raw = json.loads((root / "summary.json").read_bytes())
        if raw["git_dirty"] or raw["outer_test_status"] != "sealed":
            raise ValueError("packets require clean producing source and sealed test")
        if raw["protocol_sha256"] != protocol.sha256 or raw["shared_protocol_sha256"] != (
            document_sha256(clinical)
        ):
            raise ValueError("packet protocol differs from supplied protocol")
        identities.add((raw["git_sha"], raw["fold_plan_sha256"]))
        validate_predictions(snapshot, root, plan, protocol)
        public = dict(raw)
        public["fold_evidence"] = [
            {k: v for k, v in row.items() if k != "threshold"} for row in raw["fold_evidence"]
        ]
        audit = root / "feature-audit.json"
        if audit.exists():
            public["feature_audit"] = json.loads(audit.read_bytes())
        # Preserve runner gates byte-for-byte. Comparison readiness is a separate assembly fact.
        summaries[family] = public
        hashes = input_hashes(root)
        provenance[family] = {"files_sha256": hashes, "inventory_sha256": document_sha256(hashes)}
        for h in protocol.horizons_hours:
            for candidate in protocol.candidate_order:
                rebuilt = metric_report(packet_scores(root, h, candidate), protocol)
                published = raw["reports"][str(h)][candidate]
                if any(published[k] != v for k, v in rebuilt.items()):
                    raise ValueError("saved validation metrics differ from private predictions")
    if len(identities) != 1:
        raise ValueError("feature family source/fold identities differ")
    scoring_commit, fold_hash = next(iter(identities))
    if fold_hash != document_sha256(plan):
        raise ValueError("packet fold plan differs from verified clinical plan")
    grid = label_grid_check(snapshot, clinical)
    comparisons = {
        family: {
            str(h): {
                candidate: paired_auprc(
                    packet_scores(roots[family], h, candidate),
                    packet_scores(roots["survey-history"], h, candidate),
                    protocol,
                )
                for candidate in ("logistic", "tree")
            }
            for h in protocol.horizons_hours
        }
        for family in FAMILIES[1:]
    }
    survey_distribution = {}
    within_fold_constants = {}
    for h in protocol.horizons_hours:
        rows = packet_scores(roots["survey-history"], h, "prevalence")
        survey_distribution[str(h)] = {}
        for positive in (True, False):
            group = [s for s in rows if s.window.positive == positive]
            zero = sum(s.window.features[0] == 0 for s in group)
            survey_distribution[str(h)]["positive" if positive else "negative"] = {
                "windows": len(group),
                "zero_prior_7d_surveys": zero,
                "zero_prior_7d_surveys_fraction": zero / len(group) if group else None,
            }
        within_fold_constants[str(h)] = [
            {
                "inner_fold": i,
                "distinct_probabilities": len(
                    {
                        s.probability
                        for s in TypeAdapter(list[Score]).validate_json(
                            (
                                roots["survey-history"]
                                / f"inner-{i}-{h}h-prevalence/predictions.json"
                            ).read_bytes()
                        )
                    }
                ),
            }
            for i in range(3)
        ]
    reruns = {}
    if previous:
        if set(previous) != set(roots):
            raise ValueError("previous run comparison requires all families")
        for family, root in previous.items():
            old = json.loads((root / "summary.json").read_bytes())
            current = summaries[family]
            equal = all(
                old[k] == current[k]
                for k in (
                    "protocol_sha256",
                    "shared_protocol_sha256",
                    "fold_plan_sha256",
                    "eligible_validation",
                    "reports",
                    "selection",
                    "label_dispositions",
                )
            )
            if not equal:
                raise ValueError(
                    "source-only rerun changed scientific protocol or aggregate results"
                )
            reruns[family] = {
                "previous_packet_name": root.name,
                "current_packet_name": roots[family].name,
                "previous_scoring_commit": old["git_sha"],
                "implementation_changed_paths": subprocess.check_output(
                    [
                        "git",
                        "diff",
                        "--name-only",
                        old["git_sha"],
                        scoring_commit,
                        "--",
                        "src/hachi/models/illness",
                    ],
                    cwd=REPO,
                    text=True,
                ).splitlines(),
                "scientific_protocol_and_aggregate_results_identical": equal,
                "files_sha256": input_hashes(root),
            }
    replay_receipt = replay(list(roots.values()), scoring_commit, base_python)
    if any(input_hashes(roots[f]) != p["files_sha256"] for f, p in provenance.items()):
        raise ValueError("private evidence changed during assembly")
    return {
        "scope": "phase1-selected-retrospective-cohort-development-only",
        "source_commit": scoring_commit,
        "report_provenance": {
            "producing_commit": producer,
            "input_packets": provenance,
            "source_only_rerun_comparison": reruns,
            "transformations": [
                "fold_evidence.threshold omitted: learned operational values private",
                "feature_audit attached from its hashed extraction packet",
                "runner gates retained unchanged; assembly gates reported separately",
            ],
            "assembly_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "replay_worker_sha256": hashlib.sha256(
                Path(__file__).with_name("replay.py").read_bytes()
            ).hexdigest(),
        },
        "families": summaries,
        "protocol_document": protocol.model_dump(mode="json"),
        "paired_feature_family_auprc_vs_survey_history": comparisons,
        "past_survey_distribution_by_label": survey_distribution,
        "prevalence_within_fold_probability_counts": within_fold_constants,
        "feature_family_comparisons_status": "descriptive_development_ablation; no final selection",
        "assembly_gates": {"anomaly_derived_candidate": "development_comparison_delivered"},
        "label_grid_check": grid,
        "base_replay": replay_receipt,
        "product_status": "unavailable",
        "issue_completion": "incomplete",
        "remaining_gates": [
            "Clinical pretrained-feature comparator on same floating-clock folds/cutoffs.",
            "Adequate independently observed negatives and calibration cohort.",
            "Frozen complete-candidate final selection and one outer-test evaluation.",
            "Validated causal serving input and independent API replay.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--packet-root", type=Path, required=True)
    parser.add_argument("--suffix", default="002")
    parser.add_argument("--previous-suffix")
    parser.add_argument("--base-python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--protocol", type=Path, default=REPO / "configs/experiments/illness/phase1.toml"
    )
    parser.add_argument(
        "--clinical-protocol",
        type=Path,
        default=REPO / "configs/evaluation/stanford-phase1-clinical.json",
    )
    args = parser.parse_args(argv)
    try:
        roots = {family: args.packet_root / f"{family}-{args.suffix}" for family in FAMILIES}
        previous = (
            {family: args.packet_root / f"{family}-{args.previous_suffix}" for family in FAMILIES}
            if args.previous_suffix
            else None
        )
        report = assemble(
            args.snapshot, roots, args.base_python, args.protocol, args.clinical_protocol, previous
        )
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "phase1.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
        (args.output / "base-replay.json").write_text(
            json.dumps(report["base_replay"], indent=2, sort_keys=True) + "\n"
        )
        (args.output / "phase1.md").write_text(render(report))
        print("Sanitized evidence regenerated; outer test sealed; product unavailable.")
        return 0
    except (ValueError, OSError, KeyError, subprocess.SubprocessError):
        print("Evidence assembly failed validation or I/O; private rows withheld.")
        return 1


def render(report: dict) -> str:
    "Render every scientific table from the assembled data, without manual metric edits."
    # Public JSON is canonical; its in-memory precursor must render to the same bytes.
    report = json.loads(json.dumps(report, sort_keys=True, allow_nan=False))

    def number(value):
        return "unestimable" if value is None else f"{value:.3f}"

    families = report["families"]
    first = families["survey-history"]
    replay_result = report["base_replay"]
    grid = report["label_grid_check"]
    calibration = [
        next(e for e in first["fold_evidence"] if e["inner_fold"] == i) for i in range(3)
    ]
    labeled = "/".join(str(e["labeled_calibration_participants"]) for e in calibration)
    allocated = "/".join(str(e["calibration_participants"]) for e in calibration)
    cap = report["protocol_document"]["max_false_alert_episodes_per_30_negative_cutoff_days"]
    burdens = [
        row["metrics"]["false_alert_episodes_per_30_negative_cutoff_days"]
        for family in families.values()
        for candidates in family["reports"].values()
        for candidate, row in candidates.items()
        if candidate != "prevalence"
    ]
    failures = sum(value is not None and value > cap for value in burdens)
    lines = [
        "# Phase1 incident symptom-onset development",
        "",
        (
            "**#13 remains incomplete. Product illness probabilities remain "
            "unavailable. Outer test sealed.**"
        ),
        "",
        (
            "The target is any reported illness onset in a selected retrospective "
            "cohort mixing COVID-19, other illness, influenza B and unspecified "
            "episodes. This does not establish population calibration or an all-"
            "colds model. The 74 unlabeled controls supply zero negatives. Every "
            "observed negative comes from illness-reporting people surveyed around "
            "their illnesses."
        ),
        "",
        (
            "A negative label requires completed symptom-free surveys throughout "
            "the future window. Prior survey completion predicts future completion:"
            " past-survey features can rank negative-eligible windows without an "
            "illness signal. The causal availability rule prevents future "
            "predictors, but it does not remove this outcome-observation selection."
            " At the survey-history ceiling and with only 62 negatives at 72h, "
            "these ablations cannot establish whether physiology carries "
            "independent signal."
        ),
        "",
        "## Frozen protocol and provenance",
        "",
        f"- Clean scoring source: {report['source_commit']}; "
        f"report-producing code: {report['report_provenance']['producing_commit']}.",
        f"- Frozen task protocol SHA {first['protocol_sha256']}; "
        f"shared protocol SHA {first['shared_protocol_sha256']}.",
        f"- Labels-1 snapshot SHA {first['dataset_snapshot']['snapshot_sha256']}; "
        "labels-1 must remain retained for this pinned experiment. Labels-2 has identical "
        "task tables but is not accepted by this task protocol.",
        f"- Full roster: {first['roster_participants']} people, "
        "outer4/inner3/mintrain4/seed42/activeouter0; "
        f"plan SHA {first['fold_plan_sha256']}. Each inner fold allocates "
        "60 training / 30 validation / 31 sealed test people before task eligibility.",
        (
            f"- Calibration uses {allocated} hash-held allocated people per inner training "
            f"fold; only {labeled} contribute labels. Fit-only "
            "imputation/scaling/classifiers precede calibration-only "
            "sigmoid/threshold fitting. These small cohorts do not establish "
            "transferable calibration."
        ),
        (
            "- Frozen logistic C1, tree depth2/leaf10, calibration C1; cap 1 "
            "negative-only false-alert episode per 30 evaluable negative cutoff-"
            "days; 1000 whole-participant bootstrap replicates and 95% intervals."
        ),
        f"- Label-grid recheck: {grid['development_cutoffs']:,} development cutoffs / "
        f"{grid['onset_label_episode_comparisons']:,} comparisons / "
        f"{grid['mismatches']} mismatches. Base-only replay: "
        f"{replay_result['artifacts_reloaded']} artifacts / "
        f"{replay_result['predictions_replayed']:,} predictions / "
        f"{replay_result['decision_mismatches']} decisions differ / "
        f"max probability delta {replay_result['max_probability_difference']:.3g}.",
        (
            "- Input file hashes, assembly/worker source hashes, exact producing "
            "revisions and source-only rerun reconciliation are in phase1.json. "
            "Operational thresholds are explicitly redacted; runner gates remain "
            "unchanged and delivered comparison status is separately derived by the"
            " assembly."
        ),
        "- Prior-run reconciliation: "
        + (
            "; ".join(
                f"{r['previous_packet_name']} at {r['previous_scoring_commit']} versus "
                f"{r['current_packet_name']} at {report['source_commit']}: "
                "protocols/folds/labels/aggregate metrics/selections identical"
                for r in report["report_provenance"]["source_only_rerun_comparison"].values()
            )
            if report["report_provenance"]["source_only_rerun_comparison"]
            else "not checked; no prior packets supplied"
        ),
        "- Original -001 to -002 source change: lazy optional-dependency imports and "
        "TYPE_CHECKING packaging; no scientific feature/calibration/selection setting changed. "
        "Changed source paths are recorded beside the verified aggregate equality."
        if report["report_provenance"]["source_only_rerun_comparison"]
        and all(
            r["previous_scoring_commit"].startswith("4ac23a9")
            and report["source_commit"].startswith("722f51a")
            for r in report["report_provenance"]["source_only_rerun_comparison"].values()
        )
        else "- No source-only implementation history assertion for unchecked run pairs.",
        "",
        "## Eligible validation denominators",
        "",
        ("| Horizon | People | Incidents | Windows | Positive | Negative | Prevalence |"),
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for h, row in sorted(first["eligible_validation"].items(), key=lambda kv: int(kv[0])):
        lines.append(
            f"| {h}h | {row['participants']} | {row['incident_episodes']} | {row['windows']} | "
            f"{row['positive_windows']} | {row['negative_windows']} | {number(row['prevalence'])} |"
        )
    lines += [
        "",
        "## Past-survey observation by label",
        "",
        "| Horizon/label | Windows | Zero prior 7-day surveys | Fraction |",
        "|---|---:|---:|---:|",
    ]
    for h, groups in report["past_survey_distribution_by_label"].items():
        for label, row in groups.items():
            lines.append(
                f"| {h}h/{label} | {row['windows']} | {row['zero_prior_7d_surveys']} | "
                f"{number(row['zero_prior_7d_surveys_fraction'])} |"
            )
    lines += [
        "",
        "## Candidate results",
        "",
        (
            "Metrics are pooled across held-out inner validation people. The "
            "prevalence model assigns a different constant per fold; its pooled "
            "AUROC reflects cross-fold constants, not within-fold ranking. Within "
            "each fold it has one probability value (AUROC 0.5 when both classes "
            "exist). PPV/sensitivity/burden are conditional on evaluable windows, "
            "not population healthy time. Lead-time bounds retain the day-precision"
            " onset interval; 24h has no guaranteed positive lead time."
        ),
        "",
        (
            f"Calibration burden thresholds fail to transfer: {failures} of {len(burdens)} "
            "non-prevalence"
            " family/horizon fits exceed the validation point cap, and burden "
            "intervals span the cap even for several point estimates that pass. No "
            "transferable burden guarantee is demonstrated. Full reliability, "
            "sensitivity, lead-time and burden intervals remain in phase1.json."
        ),
        "",
    ]
    for family, summary in sorted(families.items()):
        lines += [
            f"### {family}",
            "",
            (
                "| Horizon/model | AUPRC (95% CI) | AUROC | Brier | PPV | Event "
                "sensitivity | False episodes/30 negative days (95% CI) |"
            ),
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for h, candidates in summary["reports"].items():
            for candidate, row in candidates.items():
                m, ci = row["metrics"], row["participant_bootstrap"]
                a, b = ci["auprc"], ci["false_alert_episodes_per_30_negative_cutoff_days"]
                lines.append(
                    f"| {h}h/{candidate} | {number(m['auprc'])} "
                    f"[{number(a['lower'])}, {number(a['upper'])}] | {number(m['auroc'])} | "
                    f"{number(m['brier'])} | {number(m['ppv'])} | "
                    f"{number(m['event_sensitivity'])} | "
                    f"{number(m['false_alert_episodes_per_30_negative_cutoff_days'])} "
                    f"[{number(b['lower'])}, {number(b['upper'])}] |"
                )
        lines.append("")
    lines += [
        "## Development selections",
        "",
        (
            "These candidates were selected using these validation metrics. Their "
            "displayed validation performance is therefore optimistic for "
            "selection; it is not a final held-out estimate. No cross-family "
            "product winner was selected."
        ),
        "",
        "| Family | 24h | 48h | 72h |",
        "|---|---|---|---|",
    ]
    for family, summary in sorted(families.items()):
        lines.append(
            "| "
            + family
            + " | "
            + " | ".join(
                str(summary["selection"][str(h)]["development_candidate"]) for h in (24, 48, 72)
            )
            + " |"
        )
    lines += [
        "",
        "## Descriptive feature ablations",
        "",
        "| Added family/horizon/model | Paired AUPRC difference (95% CI) |",
        "|---|---:|",
    ]
    for family, horizons in report["paired_feature_family_auprc_vs_survey_history"].items():
        for h, candidates in horizons.items():
            for candidate, row in candidates.items():
                lines.append(
                    f"| {family}/{h}h/{candidate} | {number(row['difference'])} "
                    f"[{number(row['lower'])}, {number(row['upper'])}] |"
                )
    lines += [
        "",
        (
            "No strictly positive lower bound establishes added physiology at these"
            " selected windows. This is insufficient evidence about physiology, not"
            " evidence of no physiological signal. Native extraction: 240 eligible "
            "distinct cutoffs, 123 observed rest/117 missing; anomaly 20 scored/103"
            " cold-start/117 missing. Missing values remain missing until fit-only "
            "imputation; classification coverage is not native anomaly coverage."
        ),
        "",
        "## Reproduction and private artifacts",
        "",
        (
            "Run scoring at the exact pinned clean revision using the retained "
            "labels-1 snapshot and admitted native archive. All raw samples, "
            "participant joins, learned models, predictions and thresholds remain "
            "private (0700 directories/0600 files). Survey availability is end of "
            "its shifted floating day; Z coordinates do not establish actual UTC, "
            "arrival timestamps or alignment with PMData."
        ),
        "",
        (
            "After scoring, use the committed evidence command with a baselines "
            "environment and a separate locked base-only interpreter. It archives "
            "the exact scoring source for receipt-checked replay, avoiding a "
            "source-pin bypass when the report code changes:"
        ),
        "",
        "~~~sh",
        (
            "python -I -m hachi.models.illness.evidence --snapshot "
            '"$HACHI_LABEL_SNAPSHOT" --packet-root "$HACHI_ILLNESS_PACKETS" '
            '--suffix 002 --previous-suffix 001 --base-python "$HACHI_BASE_PYTHON" '
            "--output reports/models/illness"
        ),
        "~~~",
        "",
        (
            "The current report never refits models or opens outer test. A new "
            "scoring run requires a new private directory and the original frozen "
            "protocol. serving.json remains unavailable. Full-project checks and CI"
            " are integration evidence, not population accuracy."
        ),
        "",
        "## Remaining gates",
        "",
        *["- " + gate for gate in report["remaining_gates"]],
        "",
        (
            "CMU labels now exist but have no wearables and cannot supply this "
            "wearable model. CovIdentify/Homekit2020/Evidation are unavailable for "
            "this task; no adequately sized independent wearable illness cohort has"
            " been obtained. No forbidden shared-account dataset analysis or "
            "friend-case tuning occurred."
        ),
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
