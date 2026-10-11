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
        protocol.json   the protocol (or density variant) the packet was evaluated under;
                        required for CPU artifacts, whose served gate and thinning must equal it

The packet files are copied byte-for-byte, so their hashes bind the artifact to the exact
evaluation that selected it. The served feature gate and history thinning are never taken on
trust from serving.json: they must equal the staged protocol, whose evaluation section must be
the packet's own config, and a packet's run_id label must name exactly the declared thinning.
"""

import functools
import hashlib
import json
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
from hachi.models.density.rule import AppleMinuteThinning
from hachi.storage import child

from .chronos import ENTRY_POINT as CHRONOS_ENTRY_POINT
from .chronos import ChronosServed
from .gpu import Gx10Target

MODEL_FILES = ("artifact.json", "model.json", "source-sha256.json")
PACKET_FILES = ("run.json", "split.json", "config.json")
PROTOCOL_FILE = "protocol.json"
TOP_LEVEL = frozenset({"model", "serving.json", *PACKET_FILES})
FROZEN_PROTOCOL_DIR = Path(__file__).resolve().parents[3] / "configs" / "evaluation"
SPLIT_PARAMETERS = (
    "lookback_hours",
    "horizon_hours",
    "min_history_hours",
    "embargo_hours",
    "cutoff_stride_hours",
)
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
    history_thinning: AppleMinuteThinning | None = Field(
        default=None,
        description=(
            "The evaluation thinned the model's history this way (#102's predeclared density "
            "variant, coverage in sampled minutes); served history from every source is "
            "thinned identically."
        ),
    )

    @model_validator(mode="after")
    def _policy(self) -> Self:
        if (self.input == "hourly_features") != (self.feature_policy is not None):
            raise ValueError("feature_policy is given exactly for hourly_features input")
        thinning = self.history_thinning
        if thinning is not None and (
            self.feature_policy is None
            or self.feature_policy.metric != thinning.metric
            or self.feature_policy.min_observed_count > thinning.slots_per_hour
        ):
            raise ValueError(
                "history thinning needs an hourly policy on the thinned metric whose count "
                "gate fits the hour's slots"
            )
        sources = [a.source for a in self.accepted_sources]
        if len(sources) != len(set(sources)):
            raise ValueError("each accepted source is declared once")
        for admission in self.accepted_sources:
            # Only readiness differs by source: the model's metric, aggregation and every
            # inclusion gate (coverage, count) are kept, so an admission never weakens them.
            if (
                self.feature_policy is None
                or admission.feature_policy.model_copy(
                    update={"availability_rule": self.feature_policy.availability_rule}
                )
                != self.feature_policy
            ):
                raise ValueError(
                    "an accepted source keeps the model's feature policy; only its "
                    "availability_rule may differ"
                )
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
    entries = _entries(directory)
    if entries - {PROTOCOL_FILE} != TOP_LEVEL or _entries(model_dir) != set(MODEL_FILES):
        raise ArtifactRefused("ARTIFACT_INTEGRITY_FAILED", "artifact files differ from the layout")
    files = {name: _read(model_dir / name) for name in MODEL_FILES}
    files |= {name: _read(directory / name) for name in (*PACKET_FILES, "serving.json")}
    if PROTOCOL_FILE in entries:
        files[PROTOCOL_FILE] = _read(directory / PROTOCOL_FILE)

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
        if serving.history_thinning is not None or _run_label(run) is not None:
            raise ArtifactRefused(
                "ARTIFACT_INCOMPATIBLE", "thinned-history Chronos evaluations are not served"
            )
        if PROTOCOL_FILE in files and _sha256(files[PROTOCOL_FILE]) != serving.protocol_sha256:
            raise ArtifactRefused("ARTIFACT_INCOMPATIBLE", "serving names another protocol")
        _check_chronos(model, split, serving)
    elif PROTOCOL_FILE not in files:
        raise ArtifactRefused(
            "ARTIFACT_INCOMPATIBLE",
            "a CPU artifact carries the protocol it was evaluated under; stage it with --protocol",
        )
    else:
        _check_protocol(files[PROTOCOL_FILE], run, split, evaluation, serving, model)

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


def _run_label(run: RunManifest) -> str | None:
    """The history label the PMData runner appends after the model id, if any (#107)."""
    marker = f"-{run.model.model_id}-"
    return run.run_id.rsplit(marker, 1)[1] if marker in run.run_id else None


def protocol_key(document: object) -> str:
    """Identity of a staged protocol document. A density variant is identified whole: its
    thinning rule, gates and wrapped protocol together, never the protocol alone."""
    kind = "variant" if isinstance(document, dict) and "thinning" in document else "protocol"
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return f"{kind}:{_sha256(canonical)}"


@functools.cache
def frozen_protocols() -> frozenset[str]:
    """Predeclared protocols committed under configs/evaluation: each document as written,
    and a PMData protocol also as a run's protocol.json writes it (normalized)."""
    from hachi.evaluation.pmdata_run import PMDataProtocol

    keys: set[str] = set()
    for path in sorted(FROZEN_PROTOCOL_DIR.glob("*.json")):
        document = json.loads(path.read_bytes())
        keys.add(protocol_key(document))
        if "thinning" in document:
            continue  # a variant is staged as its committed file, whole
        try:
            normalized = PMDataProtocol.model_validate_json(json.dumps(document))
        except ValueError:
            continue  # not a PMData protocol (e.g. a clinical one); its raw form is enough
        keys.add(protocol_key(normalized.model_dump(mode="json")))
    return frozenset(keys)


def _check_protocol(
    data: bytes,
    run: RunManifest,
    split: SplitManifest,
    evaluation: EvaluationConfig,
    serving: ServingSpec,
    model: ForecastModel,
) -> None:
    """Derive the evaluated gate and thinning from the staged protocol; serve nothing else.

    The protocol is a committed, predeclared PMData protocol, or a committed density variant
    taken whole (its thinning rule included), so no gate or recipe can be written by hand.
    It must name the pinned model's exact config among its comparators, with that config's
    own count gate. Its evaluation section must be the packet's config and its split
    parameters the packet's split. The served feature policy and thinning must equal it, and
    the packet's run_id label must be exactly that thinning's suffix, so neither a
    full-density packet served thinned nor a thinned packet served unthinned can be staged.
    """
    if serving.protocol_sha256 != _sha256(data):
        raise ArtifactRefused("ARTIFACT_INCOMPATIBLE", "serving names another protocol")
    try:
        document = json.loads(data)
        variant = "thinning" in document
        effective = document["protocol"] if variant else document
        policy = HourlyFeaturePolicy.model_validate_json(json.dumps(effective["feature_policy"]))
        evaluated = EvaluationConfig.model_validate_json(json.dumps(effective["evaluation"]))
        thinning = (
            AppleMinuteThinning.model_validate_json(json.dumps(document["thinning"]))
            if variant
            else None
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ArtifactRefused(
            "ARTIFACT_INCOMPATIBLE", "the staged protocol is not a served evaluation protocol"
        ) from exc
    if protocol_key(document) not in frozen_protocols():
        raise ArtifactRefused(
            "ARTIFACT_INCOMPATIBLE", "the staged protocol is not a committed, predeclared one"
        )
    comparators = [*effective.get("baselines", []), effective.get("tree")]
    config_type = type(model.config)

    def same_config(entry: object) -> bool:
        try:
            return config_type.model_validate_json(json.dumps(entry)) == model.config
        except ValueError:
            return False

    if not any(entry is not None and same_config(entry) for entry in comparators):
        raise ArtifactRefused(
            "ARTIFACT_INCOMPATIBLE", "the pinned model is not one of the protocol's comparators"
        )
    if policy.min_observed_count != model.config.min_samples_per_hour:
        raise ArtifactRefused(
            "ARTIFACT_INCOMPATIBLE", "the protocol's count gate is not the pinned model's own"
        )
    if evaluated != evaluation or any(
        key in effective and effective[key] != getattr(split, key) for key in SPLIT_PARAMETERS
    ):
        raise ArtifactRefused(
            "ARTIFACT_INCOMPATIBLE", "the packet was not evaluated under the staged protocol"
        )
    if serving.feature_policy != policy:
        raise ArtifactRefused(
            "ARTIFACT_INCOMPATIBLE", "the served feature gate differs from the evaluated one"
        )
    if serving.history_thinning != thinning:
        raise ArtifactRefused(
            "ARTIFACT_INCOMPATIBLE", "the served history thinning differs from the evaluated one"
        )
    expected = thinning.pipeline_suffix if thinning is not None else None
    if _run_label(run) != expected or (expected and not run.run_id.endswith(f"-{expected}")):
        raise ArtifactRefused(
            "ARTIFACT_INCOMPATIBLE", "the packet's history label differs from the served thinning"
        )


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
    root: Path,
    model_dir: Path,
    packet_dir: Path,
    serving: ServingSpec,
    protocol: Path | None = None,
) -> ArtifactRef:
    """Assemble a served artifact directory from a saved model and its evaluation packet.

    `protocol` is the file the evaluation ran under (the run's protocol.json, or a density
    variant). CPU artifacts need it; it is copied byte-for-byte and checked at every load.
    """
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
        if protocol is not None:
            (staging / PROTOCOL_FILE).write_bytes(_read(protocol))
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
