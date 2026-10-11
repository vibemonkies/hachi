"""Check owner-defined data-only exports without loading predictors or checkpoints."""

from pathlib import Path

from pydantic import TypeAdapter

from hachi.contracts.base import ArtifactRef, Sha256
from hachi.contracts.manifests import RunManifest, SplitManifest
from hachi.evaluation.forecast import EvaluationConfig, EvaluationResult
from hachi.evaluation.pmdata_run import PMDataProtocol
from hachi.evaluation.serialization import document_sha256
from hachi.models.baselines.artifacts import ARTIFACT, Receipt
from hachi.models.baselines.tree import FEATURES, TreeArtifact
from hachi.models.chronos.artifacts import ChronosArtifact

from .integrity import EvidenceRefused, digest, read_file, read_producing_file, verify_sources


def _protocol(bundle: Path, split: SplitManifest, config: EvaluationConfig) -> PMDataProtocol:
    protocol = PMDataProtocol.model_validate_json(read_file(bundle, "protocol.json"))
    fields = PMDataProtocol.model_fields.keys() & SplitManifest.model_fields.keys()
    scoring_fields = EvaluationConfig.model_fields.keys() - {
        "pretrained_cohort_overlap",
        "overlap_note",
    }
    if (
        protocol.expected_snapshot != split.dataset_snapshot
        or protocol.active_outer_fold != split.fold
        or protocol.folds.outer_folds != split.n_folds
        or protocol.folds.seed != split.seed
        or any(getattr(protocol, k) != getattr(split, k) for k in fields)
        or any(getattr(protocol.evaluation, k) != getattr(config, k) for k in scoring_fields)
    ):
        raise EvidenceRefused("export protocol differs from its evaluation split")
    return protocol


def verify_forecast_export(
    root: Path,
    bundle: Path,
    repo: Path,
    run: RunManifest,
    split: SplitManifest,
    result: EvaluationResult,
) -> None:
    """The immutable bundle index must have been checked by the caller first.

    Baseline, Chronos and encoder heads use the same owner-defined Receipt. Their
    model schemas and source scopes differ; parse each through its owner's type.
    No predict/load API is invoked here, so reproduction remains a separate gate.
    """
    receipt = Receipt.model_validate_json(read_file(root, "artifact.json"))
    if run.artifact != ArtifactRef(
        artifact_id=receipt.artifact_id, artifact_sha256=document_sha256(receipt)
    ):
        raise EvidenceRefused("artifact receipt differs from its run reference")
    for name, sha in receipt.files.items():
        if digest(read_file(root, name)) != sha:
            raise EvidenceRefused("artifact file differs from its receipt")
    raw = read_file(root, "model.json")
    version = TypeAdapter(dict[str, object]).validate_json(raw).get("format_version")
    sources = read_file(root, "source-sha256.json")
    config: EvaluationConfig = result.config
    if version == "chronos-2-artifact-1":
        model = ChronosArtifact.model_validate_json(raw)
        protocol = _protocol(bundle, split, config)
        pin = model.chronos.model
        if (
            model.model_id != run.model.model_id
            or model.protocol_sha256 != document_sha256(protocol)
            or model.harness_lookback_hours != split.lookback_hours
            or (model.chronos.metric, model.chronos.aggregation)
            != (config.metric, config.aggregation)
            or run.feature_order != [config.metric]
            or (run.model.checkpoint_source, run.model.checkpoint_revision, run.model.license)
            != (pin.model_id, pin.revision, pin.license)
            or run.environment_sha256 != pin.runtime_lock_sha256
        ):
            raise EvidenceRefused("Chronos export checkpoint, runtime or protocol differs")
        if model.finetuned_weights_sha256 is not None:
            # #12 must supply its actual fit receipt and the consumer interface.
            raise EvidenceRefused("fine-tuned Chronos export requires its owner fit receipt")
        if (
            model.context_policy is not None
            or model.past_covariates
            or (model.chronos.context_hours != split.lookback_hours)
        ):
            raise EvidenceRefused("extended Chronos export requires its owner context evidence")
        required = frozenset(
            {
                *(
                    f"src/hachi/models/chronos/{n}.py"
                    for n in ("adapter", "inference", "finetune", "artifacts")
                ),
                "src/hachi/evaluation/features.py",
                "src/hachi/evaluation/context.py",
                "src/hachi/evaluation/serialization.py",
                "src/hachi/contracts/causality.py",
            }
        )
        verify_sources(
            sources, repo, run.git_sha, "src/hachi/models/chronos", required_files=required
        )
        return
    fit_cutoff = min(o.cutoff for o in result.plan.origins)
    if version == "encoder-ridge-head-1":
        try:
            from hachi.models.encoders.config import EncoderExperiment
            from hachi.models.encoders.head import HANDCRAFTED, RidgeHeadArtifact
        except ModuleNotFoundError as exc:
            raise EvidenceRefused(
                "encoder receipt validation requires the baselines extra"
            ) from exc
        head = RidgeHeadArtifact.model_validate_json(raw)
        protocol = _protocol(bundle, split, config)
        experiment = EncoderExperiment.model_validate_json(read_file(bundle, "experiment.json"))
        # ProtocolRef pins the original file bytes, while saved protocol.json is
        # canonical JSON. Verify both identities instead of equating the digests.
        original_protocol = read_producing_file(repo, run.git_sha, experiment.protocol.path)
        if (
            digest(original_protocol) != experiment.protocol.sha256
            or PMDataProtocol.model_validate_json(original_protocol) != protocol
        ):
            raise EvidenceRefused("encoder experiment differs from its original pinned protocol")
        tables = TypeAdapter(dict[str, dict[str, object]]).validate_json(
            read_file(bundle, "tables.json")
        )
        candidates = [c for c in experiment.candidates if c.name == head.model_id]
        if len(candidates) != 1:
            raise EvidenceRefused("encoder export candidate is absent from the frozen experiment")
        candidate = candidates[0]
        expected_features = [
            feature
            for block in head.blocks
            for feature in (FEATURES if block == HANDCRAFTED else (f"{block}:pca",))
        ]
        expected_tables = {
            name: TypeAdapter(Sha256).validate_python(tables.get(name, {}).get("sha256"))
            for name in experiment.tables
        }
        if (
            head.fit_as_of != fit_cutoff
            or head.model_id != run.model.model_id
            or head.config != experiment.head_for(candidate)
            or head.blocks != candidate.blocks
            or head.support != experiment.tables
            or head.embedding_sha256 != expected_tables
            or (head.config.tree.metric, head.config.tree.aggregation)
            != (config.metric, config.aggregation)
            or run.feature_order != expected_features
        ):
            raise EvidenceRefused("encoder export fit, configuration, features or tables differ")
        verify_sources(sources, repo, run.git_sha, "src/hachi/models/encoders")
        verify_sources(
            sources,
            repo,
            run.git_sha,
            "src/hachi/models/encoders",
            required_files=frozenset(
                {
                    "src/hachi/models/baselines/tree.py",
                    "src/hachi/models/baselines/forecast.py",
                    "src/hachi/evaluation/features.py",
                    "src/hachi/evaluation/serialization.py",
                    "src/hachi/contracts/causality.py",
                }
            ),
        )
        return
    if version not in {"hourly-baseline-1", "causal-hourly-tree-1"}:
        raise EvidenceRefused("forecast export format has no agreed owner adapter")
    baseline = ARTIFACT.validate_json(raw)
    if baseline.fit_as_of != fit_cutoff:
        raise EvidenceRefused("artifact fit cutoff differs from its evaluation training cutoff")
    if baseline.model_id != run.model.model_id or (
        baseline.config.metric,
        baseline.config.aggregation,
    ) != (config.metric, config.aggregation):
        raise EvidenceRefused("artifact model and evaluation target disagree")
    expected_features = list(FEATURES) if isinstance(baseline, TreeArtifact) else [config.metric]
    if run.feature_order != expected_features:
        raise EvidenceRefused("artifact features differ from their run manifest")
    verify_sources(sources, repo, run.git_sha, "src/hachi/models/baselines")
