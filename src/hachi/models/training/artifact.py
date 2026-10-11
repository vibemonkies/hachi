"""Export the selected candidate as a served artifact, reload it, and verify its outputs.

For a Chronos-2 zero-shot variant the artifact holds no weights: the checkpoint pin,
runtime lock, adapter settings and context policy. Verification reloads the artifact
by its receipt, rebuilds every inner-validation request from it, requires the same
request ids the scored run used, and requires each fold's evaluation to hash to the
scored packet. A fresh GX10 run of those requests (written here) must reproduce the
forecasts exactly; `verify_reproduction` checks that afterwards.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hachi.contracts.manifests import ModelRef, RunManifest
from hachi.evaluation import evaluate_forecast, write_packet
from hachi.evaluation.serialization import document_bytes, document_sha256

from ..chronos.adapter import (
    AdapterLog,
    build_request,
    extended_builder,
    recording_factory,
    replay_factory,
)
from ..chronos.artifacts import ChronosArtifact, artifact_id_for, load_artifact, save_artifact
from ..chronos.evaluation import load_forecasts
from ..chronos.inference import canonical_bytes, file_sha256
from .pmdata import VARIANTS, Inputs, _write_private, git_state


def chronos_artifact(inputs: Inputs, variant: str) -> ChronosArtifact:
    experiment = inputs.experiment
    hours, covariates = VARIANTS[variant]
    lookback = experiment.protocol.lookback_hours
    extended = hours != lookback or bool(covariates)
    return ChronosArtifact(
        model_id=variant,
        chronos=experiment.chronos.chronos.model_copy(update={"context_hours": hours}),
        protocol_sha256=document_sha256(experiment.protocol),
        harness_lookback_hours=lookback,
        context_policy=experiment.context_policy if extended else None,
        past_covariates=list(covariates),
    )


def builder_for(artifact: ChronosArtifact, inputs: Inputs):
    """Rebuild the request builder from the reloaded artifact alone (and the data)."""
    config = artifact.chronos
    if artifact.context_policy is None:
        return lambda request: build_request(request, config)
    if document_sha256(artifact.context_policy) != document_sha256(inputs.index.policy):
        raise ValueError("artifact context policy differs from the scored experiment's")
    return extended_builder(
        config,
        inputs.index,
        context_hours=config.context_hours,
        harness_lookback_hours=artifact.harness_lookback_hours,
        covariates=artifact.past_covariates,
    )


def export_chronos(
    inputs: Inputs,
    variant: str,
    *,
    export_dir: Path,
    zeroshot_dir: Path,
    score_dir: Path,
    output: Path,
) -> dict[str, Any]:
    summary = json.loads((score_dir / "aggregate-summary.json").read_text())
    if summary["selection"]["selected"] != variant:
        raise ValueError("export only the candidate the predeclared rule selected")
    scored = summary["packets_evaluation_sha256"]
    artifact = chronos_artifact(inputs, variant)
    artifact_id = artifact_id_for(artifact)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    reference = save_artifact(output / "model", artifact, artifact_id=artifact_id)
    reloaded = load_artifact(output / "model", reference)
    if reloaded != artifact:
        raise RuntimeError("reloaded artifact differs from the saved one")
    build = builder_for(reloaded, inputs)
    forecasts = load_forecasts(export_dir / "forecast-requests.jsonl", zeroshot_dir)
    if forecasts.evidence["weights_sha256"] != reloaded.weights_sha256:
        raise ValueError("scored forecasts came from other weights than the artifact pins")
    checks = {}
    requests = {}
    results = []
    for fold, split in enumerate(inputs.splits):
        sink = {}
        evaluate_forecast(
            split,
            inputs.view.features,
            (),
            recording_factory(reloaded.chronos, sink, AdapterLog(), build),
            inputs.chronos_evaluation,
        )
        missing = set(sink) - set(forecasts.quantiles)
        if missing:
            raise ValueError("the reloaded artifact asks for contexts the scored run never saw")
        requests.update(sink)
        result = evaluate_forecast(
            split,
            inputs.view.features,
            inputs.labels,
            replay_factory(
                reloaded.chronos, forecasts.quantiles, forecasts.levels, AdapterLog(), build
            ),
            inputs.chronos_evaluation,
        )
        expected = scored[f"{variant}/inner-{fold}"]
        if document_sha256(result) != expected:
            raise ValueError(f"reloaded artifact does not reproduce inner fold {fold}")
        checks[f"inner-{fold}"] = {
            "evaluation_sha256": expected,
            "requests": len(sink),
            "reproduced": True,
        }
        results.append(result)
    rows = [requests[k].row() for k in sorted(requests)]
    reproduce = _write_private(
        output / "reproduce-requests.jsonl", b"".join(canonical_bytes(r) for r in rows)
    )
    pin = reloaded.chronos.model
    run = RunManifest(
        schema_version="0.1",
        run_id=f"outer{inputs.folds[0].outer_fold}-inner0-{variant}",
        created_at_utc=datetime.now(UTC),
        **git_state(),
        config_sha256=document_sha256(inputs.chronos_evaluation),
        dataset_snapshot=inputs.experiment.protocol.expected_snapshot,
        split_manifest_sha256=document_sha256(inputs.splits[0]),
        task="physiology_forecast",
        feature_order=[inputs.evaluation.metric, *reloaded.past_covariates],
        model=ModelRef(
            model_id=variant,
            checkpoint_source=pin.model_id,
            checkpoint_revision=pin.revision,
            license=pin.license,
        ),
        environment_sha256=pin.runtime_lock_sha256,
        seed=inputs.experiment.protocol.folds.seed,
        artifact=reference,
        metrics_paths=["evaluation.json"],
    )
    packet = write_packet(output / "packet", inputs.splits[0], run, results[0])
    receipt = {
        "format": "issue12-selected-artifact-1",
        "selected": variant,
        "pin": f"{reference.artifact_id}@{reference.artifact_sha256}",
        "artifact": reference.model_dump(),
        "weights_sha256": reloaded.weights_sha256,
        "runtime_lock_sha256": pin.runtime_lock_sha256,
        "context_policy_sha256": document_sha256(reloaded.context_policy)
        if reloaded.context_policy
        else None,
        "selection_rule_sha256": summary["selection_rule_sha256"],
        "score_summary_sha256": file_sha256(score_dir / "aggregate-summary.json"),
        "reload_checks": checks,
        "packet_sha256": packet,
        "reproduce_requests_sha256": reproduce,
        "reproduce_requests": len(rows),
        "fresh_gx10_reproduction": "pending: run inference.py on reproduce-requests.jsonl",
        "post_selection_calibration": "none: zero-shot native q0.1/q0.9, served as uncalibrated",
        "outer_test_sealed": True,
    }
    _write_private(output / "receipt.json", document_bytes(receipt))
    return receipt


def verify_reproduction(output: Path, zeroshot_dir: Path, fresh_dir: Path) -> dict[str, Any]:
    """The fresh GX10 run must answer exactly the artifact's requests with identical forecasts."""
    receipt = json.loads((output / "receipt.json").read_text())
    fresh = load_forecasts(output / "reproduce-requests.jsonl", fresh_dir)
    if fresh.evidence["weights_sha256"] != receipt["weights_sha256"]:
        raise ValueError("fresh run used other weights")
    original = {}
    with (zeroshot_dir / "predictions.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            if row["request_id"] in fresh.quantiles:
                original[row["request_id"]] = row["quantiles"]
    identical = sum(original[k] == v for k, v in fresh.quantiles.items())
    worst = max(
        abs(a - b)
        for k, rows in fresh.quantiles.items()
        for ra, rb in zip(rows, original[k], strict=True)
        for a, b in zip(ra, rb, strict=True)
    )
    result = {
        "fresh_run_predictions_sha256": fresh.evidence["predictions_sha256"],
        "requests": len(fresh.quantiles),
        "bit_identical_requests": identical,
        "max_abs_difference_bpm": worst,
        "fresh_environment": fresh.evidence.get("environment", {}).get("source_commit"),
    }
    _write_private(output / "reproduction.json", document_bytes(result))
    return result
