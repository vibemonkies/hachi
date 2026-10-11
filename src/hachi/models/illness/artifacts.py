"""Private data-only calibrated classifiers; replay uses no pickle or fitted sklearn object."""

import hashlib
import math
import os
import struct
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, model_validator

from hachi.contracts.base import ArtifactRef, Contract, Sha256
from hachi.evaluation.serialization import document_bytes, document_sha256

from .data import Window
from .metrics import Score
from .protocol import Candidate
from .training import Fitted


class Node(Contract):
    left: int
    right: int
    feature: int
    threshold: FiniteFloat
    probability: Annotated[FiniteFloat, Field(ge=0, le=1)]


class IllnessArtifact(Contract):
    format_version: Literal["illness-cpu-development-1"] = "illness-cpu-development-1"
    horizon_hours: Literal[24, 48, 72]
    candidate: Candidate
    feature_names: tuple[str, ...]
    protocol_sha256: Sha256
    feature_sha256: Sha256
    training_sha256: Sha256
    scope: Literal["selected-retrospective-cohort-development-only"]
    imputation: tuple[FiniteFloat, ...]
    missing_indicators: tuple[int, ...]
    means: tuple[FiniteFloat, ...]
    scales: tuple[Annotated[FiniteFloat, Field(gt=0)], ...]
    coefficients: tuple[FiniteFloat, ...]
    intercept: FiniteFloat
    nodes: tuple[Node, ...]
    prevalence: Annotated[FiniteFloat, Field(ge=0, le=1)]
    calibration_slope: FiniteFloat
    calibration_intercept: FiniteFloat
    threshold: Annotated[FiniteFloat, Field(ge=0, le=1.000001)]

    @model_validator(mode="after")
    def _shape(self):
        n = len(self.feature_names)
        width = n + len(self.missing_indicators)
        if n == 0 or len(set(self.feature_names)) != n:
            raise ValueError("unique nonempty feature names required")
        if self.candidate != "prevalence":
            if len(self.imputation) != n or len(self.means) != width or len(self.scales) != width:
                raise ValueError("invalid preprocessing shape")
            if len(set(self.missing_indicators)) != len(self.missing_indicators) or any(
                not 0 <= i < n for i in self.missing_indicators
            ):
                raise ValueError("invalid missing indicator index")
        if self.candidate == "logistic" and len(self.coefficients) != width:
            raise ValueError("invalid classifier coefficient shape")
        if self.candidate == "tree":
            if not self.nodes:
                raise ValueError("tree needs nodes")
            seen = set()
            stack = [0]
            while stack:
                i = stack.pop()
                if i in seen or not 0 <= i < len(self.nodes):
                    raise ValueError("tree is cyclic, shared, or out of bounds")
                seen.add(i)
                node = self.nodes[i]
                if node.left != -1 or node.right != -1:
                    if not 0 <= node.feature < width or node.left < 0 or node.right < 0:
                        raise ValueError("invalid tree branch")
                    stack.extend([node.left, node.right])
            if len(seen) != len(self.nodes):
                raise ValueError("unreachable tree nodes")
        return self

    def probability(self, features: Sequence[float | None]) -> float:
        if len(features) != len(self.feature_names):
            raise ValueError("feature order/width differs from artifact")
        raw = self.prevalence
        if self.candidate != "prevalence":
            values = [
                m if v is None else v for v, m in zip(features, self.imputation, strict=True)
            ] + [float(features[i] is None) for i in self.missing_indicators]
            scaled = [
                (v - m) / scale for v, m, scale in zip(values, self.means, self.scales, strict=True)
            ]
            if self.candidate == "logistic":
                raw = sigmoid(
                    self.intercept
                    + sum(w * v for w, v in zip(self.coefficients, scaled, strict=True))
                )
            else:
                # sklearn trees compare float32 features; reproduce that exact conversion.
                values32 = [struct.unpack("f", struct.pack("f", v))[0] for v in scaled]
                i = 0
                while self.nodes[i].left != -1:
                    node = self.nodes[i]
                    i = node.left if values32[node.feature] <= node.threshold else node.right
                raw = self.nodes[i].probability
        p = min(1 - 1e-6, max(1e-6, raw))
        return sigmoid(self.calibration_intercept + self.calibration_slope * math.log(p / (1 - p)))

    def predict(self, rows: Sequence[Window]) -> list[Score]:
        if any(r.horizon_hours != self.horizon_hours for r in rows):
            raise ValueError("prediction horizon differs from artifact")
        return [Score(r, self.probability(r.features), self.threshold) for r in rows]


def sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1 + exp)


def export(
    fitted: Fitted,
    feature_names: tuple[str, ...],
    *,
    protocol_sha256: str,
    feature_sha256: str,
    training_sha256: str,
    horizon_hours: Literal[24, 48, 72],
) -> IllnessArtifact:
    imputation, indicators, means, scales, coefficients, nodes = (), (), (), (), (), ()
    intercept = 0.0
    if fitted.estimator is not None:
        imputer, scaler, model = fitted.estimator.steps
        imputer, scaler, model = imputer[1], scaler[1], model[1]
        imputation = tuple(float(v) for v in imputer.statistics_)
        indicators = tuple(int(v) for v in imputer.indicator_.features_)
        means, scales = tuple(scaler.mean_), tuple(scaler.scale_)
        if fitted.candidate == "logistic":
            coefficients, intercept = tuple(model.coef_[0]), float(model.intercept_[0])
        else:
            tree = model.tree_
            nodes = tuple(
                Node(
                    left=int(tree.children_left[i]),
                    right=int(tree.children_right[i]),
                    feature=int(tree.feature[i]),
                    threshold=float(tree.threshold[i]),
                    probability=float(tree.value[i][0][1] / tree.value[i][0].sum()),
                )
                for i in range(tree.node_count)
            )
    return IllnessArtifact(
        horizon_hours=horizon_hours,
        candidate=fitted.candidate,
        feature_names=feature_names,
        protocol_sha256=protocol_sha256,
        feature_sha256=feature_sha256,
        training_sha256=training_sha256,
        scope="selected-retrospective-cohort-development-only",
        imputation=imputation,
        missing_indicators=indicators,
        means=means,
        scales=scales,
        coefficients=coefficients,
        intercept=intercept,
        nodes=nodes,
        prevalence=fitted.prevalence,
        calibration_slope=float(fitted.calibrator.coef_[0][0]),
        calibration_intercept=float(fitted.calibrator.intercept_[0]),
        threshold=fitted.threshold,
    )


def source_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.py"))}


class Receipt(Contract):
    artifact_id: str
    model_sha256: Sha256
    source_sha256: Sha256


def save(path: Path, artifact: IllnessArtifact, artifact_id: str) -> ArtifactRef:
    payload, sources = document_bytes(artifact), document_bytes(source_hashes())
    receipt = Receipt(
        artifact_id=artifact_id,
        model_sha256=hashlib.sha256(payload).hexdigest(),
        source_sha256=hashlib.sha256(sources).hexdigest(),
    )
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name, data in {
        "model.json": payload,
        "source-sha256.json": sources,
        "artifact.json": document_bytes(receipt),
    }.items():
        fd = os.open(path / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    return ArtifactRef(artifact_id=artifact_id, artifact_sha256=document_sha256(receipt))


def load(path: Path, expected: ArtifactRef) -> IllnessArtifact:
    receipt = Receipt.model_validate_json((path / "artifact.json").read_bytes())
    if receipt.artifact_id != expected.artifact_id or document_sha256(receipt) != (
        expected.artifact_sha256
    ):
        raise ValueError("artifact reference differs")
    payload, sources = (
        (path / "model.json").read_bytes(),
        (path / "source-sha256.json").read_bytes(),
    )
    if hashlib.sha256(payload).hexdigest() != receipt.model_sha256 or (
        hashlib.sha256(sources).hexdigest() != receipt.source_sha256
    ):
        raise ValueError("artifact checksum differs")
    if sources != document_bytes(source_hashes()):
        raise ValueError("artifact requires its identified illness implementation")
    return IllnessArtifact.model_validate_json(payload)
