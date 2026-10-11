"""Served model artifacts: loaded only after checksum, schema and feature-compatibility checks.

A served artifact is an immutable directory under the approved artifact root, pinned by the
operator as `<artifact_id>@<artifact_sha256>`:

    <artifact_root>/<artifact_id>/
        model/          artifact.json, model.json, source-sha256.json (save_artifact of
                        hachi.models.baselines or hachi.models.chronos.artifacts)
        run.json        RunManifest from the evaluation packet; names this artifact
        split.json      SplitManifest from the packet; its sha256 is run.split_manifest_sha256
        config.json     EvaluationConfig from the packet; its sha256 is run.config_sha256
        serving.json    ServingSpec: how the evaluator built model inputs

The packet files are copied byte-for-byte, so their hashes bind the artifact to the exact
evaluation that selected it.
"""

import hashlib
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, ValidationError, model_validator

from hachi.contracts.base import ArtifactRef, Contract, Sha256, Text
from hachi.contracts.manifests import RunManifest, SplitManifest
from hachi.contracts.metrics import Aggregation, Metric
from hachi.data.apple_health.hourly import AVAILABILITY_RULE as APPLE_AVAILABILITY_RULE
from hachi.evaluation import EvaluationConfig
from hachi.evaluation.features import HourlyFeaturePolicy
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.baselines import BaselineArtifact, TreeArtifact, load_artifact
from hachi.models.baselines.artifacts import Receipt
from hachi.models.baselines.tree import FEATURES
from hachi.models.chronos.artifacts import load_artifact as load_chronos_artifact
from hachi.storage import child

from .chronos import ENTRY_POINT as CHRONOS_ENTRY_POINT
from .chronos import ChronosServed
from .gpu import Gx10Target

MODEL_FILES = ("artifact.json", "model.json", "source-sha256.json")
PACKET_FILES = ("run.json", "split.json", "config.json")
TOP_LEVEL = frozenset({"model", "serving.json", *PACKET_FILES})
MAX_FILE_BYTES = 4 * 1024 * 1024

type RefusalCode = Literal["ARTIFACT_INTEGRITY_FAILED", "ARTIFACT_INCOMPATIBLE"]


class ArtifactRefused(ValueError):
    def __init__(self, code: RefusalCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class SourceAdmission(Contract):
    """Input from a source the artifact was not evaluated on, admitted explicitly.

    Admitting a source is the serving owner's transfer decision, not validation. The policy
    keeps the model's metric, aggregation and gates but uses the source's own readiness
    rule; results then carry a DEVICE_SHIFT warning naming the evaluated source.
    """

    source: Literal["apple_health"]
    feature_policy: HourlyFeaturePolicy
    rationale: Text

    @model_validator(mode="after")
    def _rule(self) -> Self:
        if self.feature_policy.availability_rule != APPLE_AVAILABILITY_RULE:
            raise ValueError("Apple Health input uses its own sealed availability rule")
        return self


class ServingSpec(Contract):
    """How to call the model the way the evaluator did. Written by the model owner."""

    format_version: Literal["hachi-serving-1"]
    task: Literal["physiology_forecast"]
    resolution: Literal["hour"]
    entry_point: Literal[
        "hachi.models.baselines.load_artifact", "hachi.models.chronos.artifacts.load_artifact"
    ]
    input: Literal["hourly_features", "observations"]
    feature_policy: HourlyFeaturePolicy | None
    interval_nominal_coverage: Annotated[float, Field(gt=0, lt=1)] | None = Field(
        default=None, description="Declared coverage of the model's intervals, if it has any."
    )
    requires_gpu: bool = False
    protocol_sha256: Sha256 | None = Field(
        default=None, description="Evaluation protocol the feature policy was taken from."
    )
    accepted_sources: list[SourceAdmission] = Field(
        default_factory=list,
        description="Other input sources this artifact may serve, each declared explicitly.",
    )

    @model_validator(mode="after")
    def _policy(self) -> Self:
        if (self.input == "hourly_features") != (self.feature_policy is not None):
            raise ValueError("feature_policy is given exactly for hourly_features input")
        sources = [a.source for a in self.accepted_sources]
        if len(sources) != len(set(sources)):
            raise ValueError("each accepted source is declared once")
        for admission in self.accepted_sources:
            policy = admission.feature_policy
            if self.feature_policy is None or (policy.metric, policy.aggregation) != (
                self.feature_policy.metric,
                self.feature_policy.aggregation,
            ):
                raise ValueError("an accepted source feeds the model's own metric and aggregation")
        return self

    def admission(self, source: str) -> SourceAdmission | None:
        return next((a for a in self.accepted_sources if a.source == source), None)


type ForecastModel = BaselineArtifact | TreeArtifact | ChronosServed


@dataclass(frozen=True)
class ServedArtifact:
    ref: ArtifactRef
    path: Path
    run: RunManifest
    split: SplitManifest
    evaluation: EvaluationConfig
    serving: ServingSpec
    model: ForecastModel

    @property
    def metric(self) -> Metric:
        return self.model.config.metric

    @property
    def aggregation(self) -> Aggregation:
        return self.model.config.aggregation


def expected_feature_order(model: ForecastModel) -> list[str]:
    return list(FEATURES) if isinstance(model, TreeArtifact) else [model.config.metric]


def _read(path: Path) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ArtifactRefused("ARTIFACT_INTEGRITY_FAILED", f"{path.name} is not a regular file")
    if info.st_size > MAX_FILE_BYTES:
        raise ArtifactRefused("ARTIFACT_INTEGRITY_FAILED", f"{path.name} exceeds its size limit")
    return path.read_bytes()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entries(directory: Path) -> set[str]:
    return {entry.name for entry in os.scandir(directory)}


def load_served_artifact(
    root: Path, pin: ArtifactRef, gx10: Gx10Target | None = None
) -> ServedArtifact:
    """Refuse incomplete, altered or incompatible artifacts; return the frozen model otherwise.

    `gx10` is where GPU-backed models (Chronos-2) run; without it they answer unavailable.
    """
    return _load_directory(child(root, pin.artifact_id), pin, gx10)


def _load_directory(
    directory: Path, pin: ArtifactRef, gx10: Gx10Target | None = None
) -> ServedArtifact:
    model_dir = directory / "model"
    if not directory.is_dir() or not model_dir.is_dir() or model_dir.is_symlink():
        raise ArtifactRefused("ARTIFACT_INTEGRITY_FAILED", "artifact directory is incomplete")
    if _entries(directory) != TOP_LEVEL or _entries(model_dir) != set(MODEL_FILES):
        raise ArtifactRefused("ARTIFACT_INTEGRITY_FAILED", "artifact files differ from the layout")
    files = {name: _read(model_dir / name) for name in MODEL_FILES}
    files |= {name: _read(directory / name) for name in (*PACKET_FILES, "serving.json")}

    # Integrity: the pinned receipt and every file it names.
    try:
        receipt = Receipt.model_validate_json(files["artifact.json"])
    except ValidationError as exc:
        raise ArtifactRefused("ARTIFACT_INTEGRITY_FAILED", "artifact receipt is invalid") from exc
    if receipt.artifact_id != pin.artifact_id or document_sha256(receipt) != pin.artifact_sha256:
        raise ArtifactRefused("ARTIFACT_INTEGRITY_FAILED", "artifact does not match its pin")
    for name, digest in receipt.files.items():
        if _sha256(files[name]) != digest:
            raise ArtifactRefused("ARTIFACT_INTEGRITY_FAILED", f"{name} checksum mismatch")

    # Schema and binding: the run manifest names this artifact and the exact packet files.
    try:
        run = RunManifest.model_validate_json(files["run.json"])
    except ValidationError as exc:
        raise ArtifactRefused(
            "ARTIFACT_INCOMPATIBLE", "run manifest does not match this schema version"
        ) from exc
    if run.artifact != pin:
        raise ArtifactRefused("ARTIFACT_INTEGRITY_FAILED", "run manifest names another artifact")
    if _sha256(files["split.json"]) != run.split_manifest_sha256:
        raise ArtifactRefused("ARTIFACT_INTEGRITY_FAILED", "split manifest hash mismatch")
    if _sha256(files["config.json"]) != run.config_sha256:
        raise ArtifactRefused("ARTIFACT_INTEGRITY_FAILED", "evaluation config hash mismatch")
    try:
        split = SplitManifest.model_validate_json(files["split.json"])
        evaluation = EvaluationConfig.model_validate_json(files["config.json"])
        serving = ServingSpec.model_validate_json(files["serving.json"])
    except ValidationError as exc:
        raise ArtifactRefused(
            "ARTIFACT_INCOMPATIBLE", "artifact manifests do not match this schema version"
        ) from exc
    if split.dataset_snapshot != run.dataset_snapshot or split.task != run.task:
        raise ArtifactRefused("ARTIFACT_INCOMPATIBLE", "split and run disagree on data or task")
    if run.task != serving.task:
        raise ArtifactRefused("ARTIFACT_INCOMPATIBLE", "artifact was not trained for this task")

    # Code: the identified implementation must be the one running here.
    model: ForecastModel
    try:
        if serving.entry_point == CHRONOS_ENTRY_POINT:
            model = ChronosServed(load_chronos_artifact(model_dir, pin), gx10)
        else:
            model = load_artifact(model_dir, pin)
    except (ValueError, OSError) as exc:
        raise ArtifactRefused(
            "ARTIFACT_INCOMPATIBLE", "artifact needs a different model implementation"
        ) from exc
    if isinstance(model, ChronosServed):
        _check_chronos(model, split, serving)

    # Features: one metric and aggregation end to end, in the order the model was trained on.
    config = model.config
    if (config.metric, config.aggregation) != (evaluation.metric, evaluation.aggregation):
        raise ArtifactRefused("ARTIFACT_INCOMPATIBLE", "model and evaluation target differ")
    policy = serving.feature_policy
    if policy is not None and (policy.metric, policy.aggregation) != (
        config.metric,
        config.aggregation,
    ):
        raise ArtifactRefused("ARTIFACT_INCOMPATIBLE", "feature policy and model target differ")
    if run.feature_order != expected_feature_order(model):
        raise ArtifactRefused("ARTIFACT_INCOMPATIBLE", "feature order differs from the model's")
    if run.model.model_id != model.model_id:
        raise ArtifactRefused("ARTIFACT_INCOMPATIBLE", "run manifest names another model")
    return ServedArtifact(pin, directory, run, split, evaluation, serving, model)


def _check_chronos(model: ChronosServed, split: SplitManifest, serving: ServingSpec) -> None:
    """Serve only what the API path reproduces exactly: zero-shot, one series, 48 h context."""
    artifact, config = model.artifact, model.config
    if artifact.context_policy or artifact.past_covariates or artifact.finetuned_weights_sha256:
        raise ArtifactRefused(
            "ARTIFACT_INCOMPATIBLE", "only zero-shot univariate Chronos artifacts are served yet"
        )
    if not serving.requires_gpu or serving.input != "hourly_features":
        raise ArtifactRefused("ARTIFACT_INCOMPATIBLE", "Chronos serves hourly features on a GPU")
    if serving.interval_nominal_coverage != config.nominal_coverage:
        raise ArtifactRefused("ARTIFACT_INCOMPATIBLE", "declared coverage differs from the model's")
    if not artifact.harness_lookback_hours == config.context_hours == split.lookback_hours:
        raise ArtifactRefused("ARTIFACT_INCOMPATIBLE", "context window differs from the protocol")
    if serving.protocol_sha256 not in (None, artifact.protocol_sha256):
        raise ArtifactRefused("ARTIFACT_INCOMPATIBLE", "serving and model name other protocols")


def stage_artifact(
    root: Path, model_dir: Path, packet_dir: Path, serving: ServingSpec
) -> ArtifactRef:
    """Assemble a served artifact directory from a saved model and its evaluation packet."""
    receipt = Receipt.model_validate_json(_read(model_dir / "artifact.json"))
    pin = ArtifactRef(artifact_id=receipt.artifact_id, artifact_sha256=document_sha256(receipt))
    run = RunManifest.model_validate_json(_read(packet_dir / "run.json"))
    if run.artifact != pin:
        raise ArtifactRefused("ARTIFACT_INTEGRITY_FAILED", "the packet's run names another model")
    target = child(root, pin.artifact_id)
    if target.exists():
        raise FileExistsError(f"{pin.artifact_id} is already staged; artifacts are immutable")
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=root))
    try:
        (staging / "model").mkdir(mode=0o700)
        for name in MODEL_FILES:
            shutil.copyfile(model_dir / name, staging / "model" / name)
        for name in PACKET_FILES:
            shutil.copyfile(packet_dir / name, staging / name)
        (staging / "serving.json").write_bytes(document_bytes(serving))
        _load_directory(staging, pin)
        for directory in (staging / "model", staging):
            for path in directory.iterdir():
                if path.is_file():
                    path.chmod(0o400)
        (staging / "model").chmod(0o500)
        staging.rename(target)
        target.chmod(0o500)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return pin
