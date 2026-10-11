"""Assemble aggregate development evidence for a model card, never final scores."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from hachi.contracts.base import ArtifactRef, Contract, DatasetSnapshotRef, GitSha, Sha256
from hachi.contracts.manifests import ModelRef, RunManifest
from hachi.evaluation.comparison import ComparisonSummary
from hachi.evaluation.metrics import Estimate, MetricReport, combine_metric_reports
from hachi.evaluation.serialization import document_sha256
from hachi.models.baselines.artifacts import Receipt

from .development import DevelopmentReceipt, _packet, validate_development
from .integrity import read_file, verify_index

METRICS = ("mae", "rmse", "median_pinball_loss", "interval_coverage", "mean_interval_width")


class ForecastModelEvidence(Contract):
    model: ModelRef
    git_sha: GitSha
    environment_sha256: Sha256
    dataset_snapshot: DatasetSnapshotRef
    config_sha256: Sha256
    candidate_settings_sha256: Sha256 | None
    run_sha256: list[Sha256]
    contributing_evaluation_sha256: list[Sha256]
    split_sha256: list[Sha256]
    source_sha256: list[Sha256]
    artifacts: list[ArtifactRef]
    scored_participants: int
    counts: dict[str, int]
    metrics: dict[str, Estimate | None]
    pretrained_cohort_overlap: Literal["not_applicable", "none", "known", "unknown"]
    overlap_note: str


class ForecastComparisonEvidence(Contract):
    comparison_sha256: Sha256
    baseline_evaluation_sha256: Sha256
    candidate_evaluation_sha256: Sha256
    split_sha256: Sha256
    counts: dict[str, int]
    definition: str
    difference: dict[str, Estimate | None]


class ForecastEvidence(Contract):
    format_version: Literal["hachi-forecast-evidence-1"] = "hachi-forecast-evidence-1"
    state: Literal["development_evidence_assembled"] = "development_evidence_assembled"
    development_receipt: DevelopmentReceipt
    development_receipt_sha256: Sha256
    models: list[ForecastModelEvidence]
    comparisons: list[ForecastComparisonEvidence]
    selection_status: Literal["pending_owner_selection"] = "pending_owner_selection"
    final_test_authorized: Literal[False] = False
    inference_reproduced: Literal[False] = False
    runtime_measurements: Literal["not_assembled"] = "not_assembled"
    limitations: list[str]


def _metrics(report: MetricReport) -> dict[str, Estimate | None]:
    return {name: getattr(report, name) for name in METRICS}


def assemble_forecast_evidence(
    root: Path,
    expected_index_sha256: str,
    repo: Path,
    *,
    artifact_bundles: Sequence[tuple[Path, str]] = (),
) -> ForecastEvidence:
    """Pool saved disjoint validation reports using the canonical aggregation helper.

    Identity-equivalent duplicate packets count once. Different model/code/config/
    environment/data identities stay separate. No labels, prediction rows, private
    memberships or coefficients are emitted. This does not establish selection,
    latency, device analysis, access approval or fresh inference reproduction.
    """
    receipt = validate_development(
        root, expected_index_sha256, repo, artifact_bundles=artifact_bundles
    )
    index = verify_index(root, expected_index_sha256)
    exports = {}
    for source, source_index in [
        (root, index),
        *[(p, verify_index(p, pin)) for p, pin in artifact_bundles],
    ]:
        for name in source_index:
            if name.endswith("/artifact.json"):
                export_receipt = Receipt.model_validate_json(read_file(source, name))
                model = TypeAdapter(dict[str, object]).validate_json(
                    read_file(source / Path(name).parent, "model.json")
                )
                # Candidate settings distinguish ablations. Learned coefficients,
                # prefixes and fitted transforms differ by fold and stay private.
                settings = {
                    k: model[k]
                    for k in (
                        "format_version",
                        "config",
                        "chronos",
                        "blocks",
                        "support",
                        "context_policy",
                        "past_covariates",
                        "finetuned_weights_sha256",
                    )
                    if k in model
                }
                exports[export_receipt.artifact_id] = document_sha256(settings)
    groups = defaultdict(list)
    seen = set()
    for relative in sorted({str(Path(n).parent) for n in index if n.endswith("/run.json")}):
        identity, result, split = _packet(root / relative, repo)
        if identity.run_sha256 in seen:
            continue
        seen.add(identity.run_sha256)
        run = RunManifest.model_validate_json(read_file(root, f"{relative}/run.json"))
        settings_sha = exports[run.artifact.artifact_id] if run.artifact is not None else None
        key = document_sha256(
            {
                "model": run.model,
                "code": run.git_sha,
                "environment": run.environment_sha256,
                "config": run.config_sha256,
                "data": run.dataset_snapshot,
                "seed": split.seed,
                "candidate_settings": settings_sha,
                "feature_order": run.feature_order,
            }
        )
        groups[key].append((run, identity, result, split, settings_sha))
    models = []
    for key in sorted(groups):
        rows = groups[key]
        run, _, result, split, settings_sha = rows[0]
        contributions = {}
        for row in rows:
            row_run, identity, _, _, _ = row
            contribution = document_sha256(
                {
                    "evaluation": identity.evaluation_sha256,
                    "split": identity.split_sha256,
                    "artifact": row_run.artifact,
                }
            )
            contributions[contribution] = row
        metric_rows = list(contributions.values())
        combined = combine_metric_reports(
            [r.metrics for _, _, r, _, _ in metric_rows], seed=split.seed
        )
        counts: Counter[str] = Counter()
        for _, _, r, _, _ in metric_rows:
            counts.update(r.counts)
        models.append(
            ForecastModelEvidence(
                model=run.model,
                git_sha=run.git_sha,
                environment_sha256=run.environment_sha256,
                dataset_snapshot=run.dataset_snapshot,
                config_sha256=run.config_sha256,
                candidate_settings_sha256=settings_sha,
                run_sha256=[i.run_sha256 for _, i, _, _, _ in rows],
                contributing_evaluation_sha256=[
                    i.evaluation_sha256 for _, i, _, _, _ in metric_rows
                ],
                split_sha256=[i.split_sha256 for _, i, _, _, _ in rows],
                source_sha256=sorted({i.source_sha256 for _, i, _, _, _ in rows}),
                artifacts=[r.artifact for r, _, _, _, _ in rows if r.artifact is not None],
                scored_participants=len(combined.subjects),
                counts=dict(counts),
                metrics=_metrics(combined),
                pretrained_cohort_overlap=result.config.pretrained_cohort_overlap,
                overlap_note=result.config.overlap_note,
            )
        )
    comparisons = []
    for name in sorted(index):
        if not name.endswith("/comparison.json"):
            continue
        summary = TypeAdapter(ComparisonSummary).validate_json(read_file(root, name))
        comparisons.append(
            ForecastComparisonEvidence(
                comparison_sha256=index[name],
                baseline_evaluation_sha256=summary.baseline_result_sha256,
                candidate_evaluation_sha256=summary.candidate_result_sha256,
                split_sha256=summary.split_manifest_sha256,
                counts=summary.counts,
                definition=summary.difference.definition,
                difference={name: getattr(summary.difference, name) for name in METRICS},
            )
        )
    return ForecastEvidence(
        development_receipt=receipt,
        development_receipt_sha256=document_sha256(receipt),
        models=models,
        comparisons=comparisons,
        limitations=[
            "Validation-only evidence; final cohort test remains sealed.",
            "Saved metric aggregation retains selection optimism; no population accuracy claim.",
            "Source access, missingness, device analysis and causality still need acceptance.",
            "Selected export, selection linkage, calibration and fresh inference remain pending.",
            "Runtime scopes and budgets are not inferred from model-only benchmarks.",
        ],
    )
