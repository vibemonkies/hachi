"""Generated evidence proves aggregation/privacy boundaries, not real model quality."""

import json
import shutil

import pytest

from hachi.evaluation.finalization.__main__ import main
from hachi.evaluation.finalization.evidence import assemble_forecast_evidence
from hachi.evaluation.finalization.integrity import EvidenceRefused
from hachi.evaluation.serialization import document_bytes, document_sha256

from .test_development import generated_bundle as generated_bundle
from .test_development import reindex


def test_aggregate_evidence_has_no_rows_and_deduplicates_runs(generated_bundle):
    root, pin, repo, packet, result = generated_bundle
    evidence = assemble_forecast_evidence(root, pin, repo)
    assert not evidence.final_test_authorized and not evidence.inference_reproduced
    assert evidence.selection_status == "pending_owner_selection"
    assert len(evidence.models) == 1
    model = evidence.models[0]
    assert model.scored_participants == result.counts["scored_participants"]
    assert model.metrics["mae"] == result.metrics.mae
    assert model.counts == result.counts
    assert evidence.development_receipt_sha256 == document_sha256(evidence.development_receipt)
    raw = document_bytes(evidence)
    for subject in [s.subject_id for s in result.metrics.subjects]:
        assert subject.encode() not in raw
    assert b'"subjects"' not in raw and b'"predictions"' not in raw
    shutil.copytree(packet, packet.parent / "duplicate")
    duplicated = assemble_forecast_evidence(root, reindex(root), repo)
    assert duplicated.models == evidence.models
    alternate = packet.parent / "duplicate/run.json"
    doc = json.loads(alternate.read_bytes())
    doc["run_id"] = "alternate-reference"
    alternate.write_bytes(document_bytes(doc))
    relabelled = assemble_forecast_evidence(root, reindex(root), repo)
    assert relabelled.models[0].counts == model.counts
    assert len(relabelled.models[0].run_sha256) == 2
    assert len(relabelled.models[0].contributing_evaluation_sha256) == 1


def test_same_model_id_with_distinct_candidate_settings_is_never_pooled(generated_bundle):
    import subprocess
    from pathlib import Path

    import hachi.models.baselines.artifacts as implementation
    from hachi.contracts.manifests import RunManifest
    from hachi.evaluation import TrainingPrefix
    from hachi.models.baselines import BaselineConfig, fit_baseline, save_artifact

    from ..conftest import BASE

    root, _, repo, packet, _ = generated_bundle
    package = Path(implementation.__file__).parents[2]
    shutil.copytree(
        package,
        repo / "src/hachi",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    subprocess.run(["git", "add", "src"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Generated Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "Generated baseline sources",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    original = RunManifest.model_validate_json((packet / "run.json").read_bytes())
    duplicate = packet.parent / "different-settings"
    shutil.copytree(packet, duplicate)
    for target, minimum in ((packet, 1), (duplicate, 2)):
        artifact = fit_baseline(
            TrainingPrefix(BASE, ("generated-train",), ()),
            BaselineConfig(
                method="last_valid",
                metric="heart_rate",
                aggregation="mean",
                min_samples_per_hour=minimum,
            ),
        )
        ref = save_artifact(
            root / f"fold/models/variant-{minimum}", artifact, artifact_id=f"variant-{minimum}"
        )
        run = original.model_copy(
            update={
                "run_id": f"variant-{minimum}",
                "git_sha": sha,
                "model": original.model.model_copy(update={"model_id": artifact.model_id}),
                "artifact": ref,
            }
        )
        (target / "run.json").write_bytes(document_bytes(run))
    evidence = assemble_forecast_evidence(root, reindex(root), repo)
    assert len(evidence.models) == 2
    assert len({m.candidate_settings_sha256 for m in evidence.models}) == 2
    assert len({m.model.model_id for m in evidence.models}) == 1


def test_evidence_refuses_invalid_original_bytes_and_cli_preserves_inputs(
    generated_bundle, tmp_path, capsys
):
    root, pin, repo, packet, _ = generated_bundle
    output = tmp_path / "aggregate"
    args = [
        "evidence",
        "--bundle",
        str(root),
        "--expected-index-sha256",
        pin,
        "--repo",
        str(repo),
        "--output",
        str(output),
    ]
    assert main(args) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["models"] == 1 and not status["final_test_authorized"]
    assert main(args) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    (packet / "evaluation.json").write_bytes(b'{"private-row":"do-not-emit"}')
    with pytest.raises(EvidenceRefused):
        assemble_forecast_evidence(root, pin, repo)
    assert main([*args[:-1], str(tmp_path / "refused")]) == 1
    assert "do-not-emit" not in capsys.readouterr().out


@pytest.mark.parametrize("mutation", ["count", "difference", "conserved_errors"])
def test_paired_evidence_cannot_publish_fabricated_support_or_estimates(
    generated_bundle, cohort, mutation
):
    from hachi.contracts.manifests import RunManifest, SplitManifest
    from hachi.evaluation import ForecastEstimate, compare_forecasts, write_comparison_packet

    root, _, repo, packet, result = generated_bundle
    split = SplitManifest.model_validate_json((packet / "split.json").read_bytes())
    baseline = RunManifest.model_validate_json((packet / "run.json").read_bytes())
    candidate = baseline.model_copy(
        update={
            "run_id": "generated-candidate",
            "model": baseline.model.model_copy(update={"model_id": "generated-candidate"}),
        }
    )
    compared = compare_forecasts(
        split,
        *cohort,
        lambda _: lambda r: [ForecastEstimate(median=60.0)] * len(r.targets),
        lambda _: lambda r: [ForecastEstimate(median=60.0)] * len(r.targets),
        baseline_config=result.config,
        candidate_config=result.config,
    )
    pair = root / "fold/comparisons/pair"
    write_comparison_packet(pair, split, baseline, candidate, compared)
    accepted = assemble_forecast_evidence(root, reindex(root), repo)
    assert accepted.comparisons[0].counts["paired_points"] > 0
    doc = json.loads((pair / "comparison.json").read_bytes())
    if mutation == "count":
        doc["counts"]["paired_points"] = -1
    elif mutation == "difference":
        doc["difference"]["mae"]["value"] = 999.0
    else:
        from dataclasses import replace

        from hachi.evaluation.comparison import _paired_metrics
        from hachi.evaluation.metrics import combine_metric_reports

        report = compared.summary.baseline_on_paired_targets
        first = report.subjects[0]
        changed = replace(
            first,
            mae=first.mae + 2,
            rmse=first.rmse + 2,
            median_pinball_loss=first.median_pinball_loss + 1,
        )
        report = combine_metric_reports(
            [replace(report, subjects=(changed, *report.subjects[1:]))], seed=split.seed
        )
        summary = replace(
            compared.summary,
            baseline_on_paired_targets=report,
            difference=_paired_metrics(
                report, compared.summary.candidate_on_paired_targets, result.config, split.seed
            ),
        )
        doc = json.loads(document_bytes(summary))
    (pair / "comparison.json").write_bytes(document_bytes(doc))
    with pytest.raises(EvidenceRefused):
        assemble_forecast_evidence(root, reindex(root), repo)
