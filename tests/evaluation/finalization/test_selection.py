"""Generated owner-format linkage evidence; no private inputs or checkpoint inference."""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from hachi.contracts.manifests import ModelRef, RunManifest, SplitManifest
from hachi.evaluation import (
    ForecastEstimate,
    compare_forecasts,
    write_comparison_packet,
    write_packet,
)
from hachi.evaluation.finalization.integrity import EvidenceRefused, digest, verify_index
from hachi.evaluation.finalization.owner12 import owner_experiment
from hachi.evaluation.finalization.selection import validate_selection_links
from hachi.evaluation.metrics import bootstrap_participant_mean, combine_metric_reports
from hachi.evaluation.pmdata_run import PMDataProtocol
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.chronos.pmdata import ChronosPMDataConfig
from hachi.models.ensemble.selection import Challenge, SelectionRule, select

from ..conftest import BASE
from .test_development import generated_bundle as generated_bundle
from .test_development import reindex


@dataclass
class GeneratedSelection:
    root: Path
    repo: Path
    index: Path
    summary: dict
    index_pin: str = ""
    summary_pin: str = ""

    def seal(self):
        # The original owner summary is pretty JSON, while canonical packets are
        # written through the shared serializers. Preserve that format distinction.
        (self.root / "aggregate-summary.json").write_text(
            json.dumps(self.summary, indent=2, sort_keys=True) + "\n"
        )
        reindex(self.root)
        top = self.root / "sha256.json"
        self.index.write_bytes(top.read_bytes())
        top.unlink()
        self.index_pin = digest(self.index.read_bytes())
        self.summary_pin = digest((self.root / "aggregate-summary.json").read_bytes())
        return self

    def validate(self):
        return validate_selection_links(
            self.root,
            self.index_pin,
            self.repo,
            index_path=self.index,
            expected_summary_sha256=self.summary_pin,
        )


@pytest.fixture
def generated_selection(generated_bundle, manifest, cohort):
    root, _, repo, _, result = generated_bundle
    shutil.rmtree(root)
    root.mkdir()
    import hachi.models.training.pmdata as producer

    package = Path(producer.__file__).parents[2]
    shutil.copytree(
        package,
        repo / "src/hachi",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    actual = Path(__file__).resolve().parents[3]
    protocol = PMDataProtocol.model_validate_json(
        (actual / "configs/evaluation/pmdata-hourly-validation.json").read_bytes()
    )
    snapshot = manifest.dataset_snapshot.model_copy(
        update={"dataset_id": "pmdata", "dataset_version": "generated-version"}
    )
    protocol = protocol.model_copy(
        update={
            "expected_snapshot": snapshot,
            "evaluation": result.config,
            "folds": protocol.folds.model_copy(update={"inner_folds": 2, "min_train_subjects": 1}),
            **{
                name: getattr(manifest, name)
                for name in PMDataProtocol.model_fields.keys() & SplitManifest.model_fields.keys()
            },
        }
    )
    protocol = PMDataProtocol.model_validate_json(document_bytes(protocol))
    rule = SelectionRule.model_validate_json(
        (actual / "configs/experiments/pmdata-hourly-selection.json").read_bytes()
    ).model_copy(
        update={
            "protocol_sha256": document_sha256(protocol),
            "candidate_order": [
                "generated-default",
                "generated-challenger",
                "generated-unavailable",
            ],
            "ablations_not_candidates": [],
        }
    )
    chronos = ChronosPMDataConfig.model_validate_json(
        (actual / "configs/models/chronos/pmdata-hourly-hr.json").read_bytes()
    )
    chronos = chronos.model_copy(
        update={
            "protocol_sha256": document_sha256(protocol),
            "chronos": chronos.chronos.model_copy(
                update={"context_hours": protocol.lookback_hours}
            ),
        }
    )
    adaptation = json.loads(
        (actual / "configs/experiments/pmdata-hourly-adaptation.json").read_bytes()
    )
    adaptation.update(
        protocol_sha256=document_sha256(protocol), selection_rule_sha256=document_sha256(rule)
    )
    for relative, document in (
        ("configs/evaluation/pmdata-hourly-validation.json", protocol),
        ("configs/experiments/pmdata-hourly-selection.json", rule),
        ("configs/models/chronos/pmdata-hourly-hr.json", chronos),
        ("configs/experiments/pmdata-hourly-adaptation.json", adaptation),
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(document_bytes(document))
    shutil.copyfile(actual / "uv.lock", repo / "uv.lock")
    environment = digest((repo / "uv.lock").read_bytes())
    subprocess.run(
        ["git", "add", "src", "configs", "uv.lock"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Generated Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "Generated owner experiment",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    owner = owner_experiment(repo, revision)
    cohort = tuple(
        [row.model_copy(update={"dataset_id": "pmdata"}) for row in rows] for rows in cohort
    )
    development = sorted(manifest.train_subjects + manifest.validation_subjects)
    results, comparisons, links, hashes = {}, [], {}, {}

    def run(name, fold, split, evaluation):
        return RunManifest(
            schema_version="0.1",
            run_id=f"{name}-inner-{fold}",
            created_at_utc=BASE,
            git_sha=revision,
            git_dirty=False,
            config_sha256=document_sha256(evaluation.config),
            dataset_snapshot=snapshot,
            split_manifest_sha256=document_sha256(split),
            task=split.task,
            feature_order=["heart_rate"],
            model=ModelRef(
                model_id=name, checkpoint_source=None, checkpoint_revision=None, license=None
            ),
            environment_sha256=environment,
            seed=split.seed,
            artifact=None,
            metrics_paths=["evaluation.json"],
        )

    for fold in range(2):
        validation = development[fold::2]
        split = manifest.model_copy(
            update={
                "manifest_id": f"generated-inner-{fold}",
                "dataset_snapshot": snapshot,
                "fold": protocol.active_outer_fold,
                "n_folds": protocol.folds.outer_folds,
                "validation_subjects": validation,
                "train_subjects": sorted(set(development) - set(validation)),
            }
        )
        comparison = compare_forecasts(
            split,
            *cohort,
            lambda _: lambda row: [ForecastEstimate(median=60.0)] * len(row.targets),
            lambda _: (
                lambda row: (
                    [ForecastEstimate(median=61.0, lower=60.0, upper=62.0)] * len(row.targets)
                )
            ),
            baseline_config=result.config,
            candidate_config=result.config,
        )
        comparisons.append(comparison)
        baseline_run = run("generated-default", fold, split, comparison.baseline)
        candidate_run = run("generated-challenger", fold, split, comparison.candidate)
        for name, evaluation, descriptor in (
            ("generated-default", comparison.baseline, baseline_run),
            ("generated-challenger", comparison.candidate, candidate_run),
        ):
            key = f"{name}/inner-{fold}"
            write_packet(root / "candidates" / key, split, descriptor, evaluation)
            hashes[key] = document_sha256(evaluation)
            results[key] = evaluation
        relative = f"chain/generated-default__vs__generated-challenger/inner-{fold}"
        packet = root / relative
        write_comparison_packet(packet, split, baseline_run, candidate_run, comparison)
        links[f"inner-{fold}"] = {
            "path": relative,
            **{
                name: digest((packet / name).read_bytes())
                for name in ("comparison.json", "sha256.json")
            },
        }
    pooled = {}
    for name in rule.candidate_order[:2]:
        rows = [results[f"{name}/inner-{fold}"] for fold in range(2)]
        metrics = combine_metric_reports([row.metrics for row in rows], seed=protocol.folds.seed)
        pooled[name] = {
            "family": "comparator",
            **{
                key: json.loads(document_bytes(getattr(metrics, key)))
                for key in ("mae", "rmse", "interval_coverage", "mean_interval_width")
            },
            "abstention_share": 0.0,
            "counts": {
                key: sum(row.counts[key] for row in rows)
                for key in (
                    "expected_points",
                    "scored_points",
                    "abstained_points",
                    "missing_labels",
                    "insufficient_history_points",
                    "predicted_origins",
                )
            },
        }
    cost = {"latency_p95_seconds": 0.01, "peak_memory_bytes": 1024}
    challenge = Challenge(
        candidate="generated-challenger",
        incumbent="generated-default",
        paired_points=sum(c.summary.counts["paired_points"] for c in comparisons),
        paired_mae=bootstrap_participant_mean(
            [s.mae for c in comparisons for s in c.summary.difference.subjects],
            samples=protocol.evaluation.bootstrap_samples,
            confidence=protocol.evaluation.confidence,
            seed=protocol.folds.seed,
        ),
        paired_decile_loss=bootstrap_participant_mean(
            [-1.0] * len(development),
            samples=protocol.evaluation.bootstrap_samples,
            confidence=protocol.evaluation.confidence,
            seed=protocol.folds.seed,
        ),
        coverage=combine_metric_reports(
            [c.candidate.metrics for c in comparisons], seed=protocol.folds.seed
        ).interval_coverage,
        abstention_share=0.0,
        incumbent_abstention_share=0.0,
        **cost,
    )
    log = select(rule, document_sha256(rule), rule.candidate_order[:2], lambda *_: challenge)
    summary = {
        "format": "issue12-pmdata-score-1",
        "git_sha": revision,
        "git_dirty": False,
        "environment_sha256": environment,
        "export_git_sha": revision,
        "protocol_sha256": document_sha256(protocol),
        "selection_rule_sha256": document_sha256(rule),
        "adaptation_sha256": owner.adaptation_sha256,
        "context_policy_sha256": document_sha256(owner.context),
        "dataset_snapshot": snapshot.model_dump(mode="json"),
        "outer_test_sealed": True,
        "validation_participants": len(development),
        "inner_folds": 2,
        "requests": {},
        "zero_shot_predictions_sha256": "c" * 64,
        "embeddings_sha256": "d" * 64,
        "candidates": pooled,
        "costs": {"generated-challenger": cost},
        "selection": {
            "rule_sha256": log.rule_sha256,
            "selected": log.selected,
            "steps": [
                {
                    "candidate": step.candidate,
                    "incumbent": step.incumbent,
                    "status": step.status,
                    "gates": step.gates,
                    "evidence": json.loads(document_bytes(step.challenge)),
                    "packets": links if step.challenge else {},
                }
                for step in log.steps
            ],
        },
        "packets_evaluation_sha256": hashes,
        "ablations": {},
        "external_11": {},
        "ensemble_support": {},
        "residual_offsets": {},
        "finetune": None,
    }
    return GeneratedSelection(root, repo, root.parent / "original-score-index.json", summary).seal()


def test_original_selection_links_are_verified_without_selection_or_test_authority(
    generated_selection,
):
    fixture = generated_selection
    evidence = fixture.validate()
    assert evidence.state == "development_selection_links_verified"
    assert evidence.owner_reported_selected == fixture.summary["selection"]["selected"]
    assert not evidence.scientific_selection_accepted and not evidence.final_test_authorized
    assert not evidence.development_receipt.final_test_authorized
    assert len(evidence.selected_evaluation_sha256) == 2
    assert len(evidence.development_receipt.evaluations) == 4
    assert evidence.steps[1].status == "not_available" and not evidence.steps[1].packets
    assert evidence.score_summary_sha256 == fixture.summary_pin
    assert evidence.score_index_sha256 == fixture.index_pin
    assert set(evidence.owner_documents_sha256) == {
        "configs/evaluation/pmdata-hourly-validation.json",
        "configs/experiments/pmdata-hourly-selection.json",
        "configs/models/chronos/pmdata-hourly-hr.json",
        "configs/experiments/pmdata-hourly-adaptation.json",
        "src/hachi/models/training/pmdata.py",
    }
    # No participant rows, observations, predictions or learned coefficients are
    # copied into the new data-only aggregate result.
    exported = document_bytes(evidence)
    assert all(f'"synthetic-{i}"'.encode() not in exported for i in range(6))
    assert b'"predictions":' not in exported and b'"coefficients":' not in exported


@pytest.mark.parametrize(
    "mutation",
    [
        "candidate_hash",
        "paired_index",
        "paired_path",
        "pooled_counts",
        "pooled_metric",
        "gates",
        "status",
        "order",
        "selected",
        "protocol",
        "environment",
        "adaptation",
        "context",
        "opened_summary",
        "missing_fold",
    ],
)
def test_rehashed_summary_cannot_rewrite_linked_selection_evidence(generated_selection, mutation):
    fixture = generated_selection
    summary = fixture.summary
    step = summary["selection"]["steps"][0]
    if mutation == "candidate_hash":
        summary["packets_evaluation_sha256"]["generated-challenger/inner-0"] = "e" * 64
    elif mutation == "paired_index":
        step["packets"]["inner-0"]["sha256.json"] = "e" * 64
    elif mutation == "paired_path":
        step["packets"]["inner-0"]["path"] = step["packets"]["inner-1"]["path"]
    elif mutation == "pooled_counts":
        summary["candidates"]["generated-challenger"]["counts"]["scored_points"] += 1
    elif mutation == "pooled_metric":
        summary["candidates"]["generated-challenger"]["mae"]["value"] += 1
    elif mutation == "gates":
        step["gates"]["coverage_in_range"] = not step["gates"]["coverage_in_range"]
    elif mutation == "status":
        step["status"] = "promoted"
    elif mutation == "order":
        summary["selection"]["steps"].reverse()
    elif mutation == "selected":
        summary["selection"]["selected"] = "generated-challenger"
    elif mutation == "protocol":
        summary["protocol_sha256"] = "e" * 64
    elif mutation == "environment":
        summary["environment_sha256"] = "e" * 64
    elif mutation == "adaptation":
        summary["adaptation_sha256"] = "e" * 64
    elif mutation == "context":
        summary["context_policy_sha256"] = "e" * 64
    elif mutation == "opened_summary":
        summary["outer_test_sealed"] = False
    else:
        del summary["packets_evaluation_sha256"]["generated-challenger/inner-0"]
    fixture.seal()
    with pytest.raises(ValueError):
        fixture.validate()


def test_rehashed_open_test_packet_is_refused(generated_selection):
    fixture = generated_selection
    path = fixture.root / "candidates/generated-challenger/inner-0/split.json"
    split = json.loads(path.read_bytes())
    split["test_opened_at_utc"] = "2026-10-11T00:00:00Z"
    path.write_bytes(document_bytes(split))
    fixture.seal()
    with pytest.raises(EvidenceRefused, match="opened or scored test"):
        fixture.validate()


def test_noncanonical_candidate_evaluation_cannot_acquire_a_canonical_identity(generated_selection):
    fixture = generated_selection
    key = "generated-challenger/inner-0"
    path = fixture.root / "candidates" / key / "evaluation.json"
    path.write_text(json.dumps(json.loads(path.read_bytes()), indent=2) + "\n")
    fixture.summary["packets_evaluation_sha256"][key] = digest(path.read_bytes())
    fixture.seal()
    with pytest.raises(EvidenceRefused, match=r"inconsistent evaluations|canonical packet"):
        fixture.validate()


def test_original_external_summary_pin_survives_inventory_rehash(generated_selection):
    fixture = generated_selection
    original = fixture.summary_pin
    fixture.summary["unverified_owner_note"] = "generated ancillary metadata"
    fixture.seal()
    fixture.summary_pin = original
    with pytest.raises(EvidenceRefused, match="original external pin"):
        fixture.validate()


def test_original_external_inventory_pin_and_completeness(generated_selection):
    fixture = generated_selection
    assert verify_index(fixture.root, fixture.index_pin, index_path=fixture.index)
    with pytest.raises(EvidenceRefused, match="expected checksum"):
        verify_index(fixture.root, "e" * 64, index_path=fixture.index)
    (fixture.root / "unindexed-owner-note.json").write_text("{}")
    with pytest.raises(EvidenceRefused, match="unindexed"):
        fixture.validate()


def test_external_inventory_cannot_be_moved_inside_the_bundle(generated_selection):
    fixture = generated_selection
    internal = fixture.root / "inventory.json"
    internal.write_bytes(fixture.index.read_bytes())
    with pytest.raises(EvidenceRefused, match="outside its immutable bundle"):
        verify_index(fixture.root, fixture.index_pin, index_path=internal)


def _refresh_original_pair_links(fixture):
    reindex(fixture.root)
    for step in fixture.summary["selection"]["steps"]:
        for link in step["packets"].values():
            for name in ("comparison.json", "sha256.json"):
                link[name] = digest((fixture.root / link["path"] / name).read_bytes())
    fixture.seal()


@pytest.mark.parametrize("mutation", ["model", "environment", "revision"])
def test_rehashed_embedded_paired_run_cannot_change_its_provenance(generated_selection, mutation):
    fixture = generated_selection
    link = fixture.summary["selection"]["steps"][0]["packets"]["inner-0"]
    path = fixture.root / link["path"] / "baseline/run.json"
    run = json.loads(path.read_bytes())
    if mutation == "model":
        run["model"]["model_id"] = "generated-unrelated-model"
    elif mutation == "environment":
        run["environment_sha256"] = "e" * 64
    else:
        run["git_sha"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD^"], cwd=fixture.repo, text=True
        ).strip()
    path.write_bytes(document_bytes(run))
    standalone = fixture.root / "candidates/generated-default/inner-0/run.json"
    original_candidate_bytes = standalone.read_bytes()
    _refresh_original_pair_links(fixture)
    assert standalone.read_bytes() == original_candidate_bytes
    with pytest.raises(EvidenceRefused, match="paired run provenance"):
        fixture.validate()


def _commit_generated_adaptation(fixture, adaptation, message):
    path = fixture.repo / "configs/experiments/pmdata-hourly-adaptation.json"
    path.write_bytes(document_bytes(adaptation))
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Generated Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qam",
            message,
        ],
        cwd=fixture.repo,
        check=True,
        capture_output=True,
    )
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=fixture.repo, text=True
    ).strip()


def _rebind_generated_score_revision(fixture, revision):
    # Only fixture manifests change; original metric/evaluation bytes remain fixed.
    for path in fixture.root.rglob("run.json"):
        run = json.loads(path.read_bytes())
        run["git_sha"] = revision
        path.write_bytes(document_bytes(run))
    fixture.summary["git_sha"] = revision
    _refresh_original_pair_links(fixture)


@pytest.fixture
def generated_amended_selection(generated_selection):
    fixture = generated_selection
    path = fixture.repo / "configs/experiments/pmdata-hourly-adaptation.json"
    scoring = json.loads(path.read_bytes())
    exported = {key: value for key, value in scoring.items() if key != "amendment_2"}
    export_revision = _commit_generated_adaptation(
        fixture, exported, "Generated pre-amendment export"
    )
    score_revision = _commit_generated_adaptation(fixture, scoring, "Generated amended scoring")
    fixture.summary["export_git_sha"] = export_revision
    fixture.summary["adaptation_sha256"] = digest(document_bytes(exported))
    _rebind_generated_score_revision(fixture, score_revision)
    return fixture


def test_export_and_amended_score_bind_both_original_document_sets(generated_amended_selection):
    fixture = generated_amended_selection
    evidence = fixture.validate()
    path = "configs/experiments/pmdata-hourly-adaptation.json"
    assert evidence.export_git_sha == fixture.summary["export_git_sha"]
    assert evidence.producing_git_sha == fixture.summary["git_sha"]
    assert evidence.export_git_sha != evidence.producing_git_sha
    assert evidence.adaptation_sha256 == fixture.summary["adaptation_sha256"]
    assert evidence.export_documents_sha256[path] == evidence.adaptation_sha256
    assert evidence.owner_documents_sha256[path] != evidence.export_documents_sha256[path]
    assert {
        key
        for key in evidence.owner_documents_sha256
        if evidence.owner_documents_sha256[key] != evidence.export_documents_sha256[key]
    } == {path}
    assert not evidence.scientific_selection_accepted and not evidence.final_test_authorized


@pytest.mark.parametrize("mutation", ["non_amendment_setting", "score_pin_for_export"])
def test_rehashed_score_cannot_hide_changes_outside_its_recorded_amendment(
    generated_amended_selection, mutation
):
    fixture = generated_amended_selection
    path = fixture.repo / "configs/experiments/pmdata-hourly-adaptation.json"
    if mutation == "non_amendment_setting":
        scoring = json.loads(path.read_bytes())
        scoring["serving_refit"] = "Generated changed serving choice outside amendment_2"
        revision = _commit_generated_adaptation(fixture, scoring, "Generated unrecorded setting")
        _rebind_generated_score_revision(fixture, revision)
    else:
        fixture.summary["adaptation_sha256"] = digest(path.read_bytes())
        fixture.seal()
    with pytest.raises(EvidenceRefused, match="producing experiment"):
        fixture.validate()
