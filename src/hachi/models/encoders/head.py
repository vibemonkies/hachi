"""One simple trained head for every input set: phase-modulated ridge regression.

The same head is fitted on the #9 handcrafted features alone, on frozen embeddings alone, or on
both, so a difference between them is a difference of inputs, not of heads. Training pairs
follow the tree baseline's causal construction exactly (labels and origins inside the
evaluator's training prefix); embeddings come from precomputed causal windows looked up at the
origin, never later. Training rows are restricted to origins where every embedding the
experiment compares is available, so all candidates fit and score on one support.
"""

import hashlib
import math
from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

import numpy as np
from pydantic import Field, model_validator

from hachi.contracts.base import Contract, Sha256, UtcDatetime
from hachi.contracts.metrics import METRICS, check_metric_value
from hachi.evaluation import (
    ForecastEstimate,
    ForecastInput,
    ForecastObservation,
    Predictor,
    PredictorFactory,
    TrainingPrefix,
)
from hachi.evaluation.serialization import document_sha256
from hachi.models.baselines.forecast import HOUR, BaselineConfig, hourly_values
from hachi.models.baselines.tree import FEATURES, TreeConfig, _features

HANDCRAFTED = "handcrafted"


class HeadConfig(Contract):
    tree: TreeConfig
    ridge_alpha: Annotated[float, Field(gt=0)]
    pca_components: Annotated[int, Field(ge=1)]
    phase_interactions: bool = True
    max_staleness_hours: Annotated[int, Field(ge=1)]


@dataclass(frozen=True)
class EmbeddingTable:
    """Frozen per-window vectors, each final at its as-of instant."""

    name: str
    subject_ids: tuple[str, ...]
    as_of_utc: tuple[datetime, ...]
    vectors: np.ndarray
    sha256: str

    def __post_init__(self) -> None:
        if self.vectors.ndim != 2 or len(self.vectors) != len(self.subject_ids):
            raise ValueError("one embedding row per window")
        if not np.isfinite(self.vectors).all():
            raise ValueError("embedding tables must be finite")
        rows: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
        for i, (s, a) in enumerate(zip(self.subject_ids, self.as_of_utc, strict=True)):
            rows[s].append((a, i))
        index = {s: sorted(v) for s, v in rows.items()}
        if any(len({a for a, _ in v}) != len(v) for v in index.values()):
            raise ValueError("duplicate subject/as-of embedding rows")
        object.__setattr__(self, "_index", index)

    @classmethod
    def from_arrays(
        cls,
        name: str,
        subject_ids: Sequence[str],
        as_of_utc: Sequence[datetime],
        vectors: np.ndarray,
    ) -> "EmbeddingTable":
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        h = hashlib.sha256()
        for s, a in zip(subject_ids, as_of_utc, strict=True):
            h.update(f"{s}\x00{a.isoformat()}\n".encode())
        h.update(vectors.tobytes())
        return cls(name, tuple(subject_ids), tuple(as_of_utc), vectors, h.hexdigest())

    @classmethod
    def load(cls, name: str, path: Path) -> "EmbeddingTable":
        with np.load(path, allow_pickle=False) as data:
            return cls.from_arrays(
                name,
                [str(s) for s in data["subject_ids"]],
                [datetime.fromisoformat(str(a)).astimezone(UTC) for a in data["as_of_utc"]],
                data["embeddings"],
            )

    def lookup(self, subject_id: str, cutoff: datetime, max_staleness_hours: int) -> int | None:
        rows = self._index.get(subject_id, [])  # type: ignore[attr-defined]
        position = bisect_left(rows, (cutoff, len(self.subject_ids)))
        if position == 0:
            return None
        as_of, index = rows[position - 1]
        if as_of > cutoff or cutoff - as_of > max_staleness_hours * HOUR:
            return None
        return index


@dataclass(frozen=True)
class TrainingPairs:
    subjects: tuple[str, ...]
    origins: tuple[datetime, ...]
    targets: tuple[datetime, ...]
    handcrafted: np.ndarray
    labels: np.ndarray


def training_pairs(training: TrainingPrefix, config: TreeConfig) -> TrainingPairs:
    """The tree baseline's causal pairs, keeping each pair's subject, origin and target."""
    by_subject: dict[str, list[ForecastObservation]] = defaultdict(list)
    for row in training.observations:
        by_subject[row.subject_id].append(row)
    bin_config = BaselineConfig(
        method="last_valid",
        metric=config.metric,
        aggregation=config.aggregation,
        min_samples_per_hour=config.min_samples_per_hour,
    )
    subjects: list[str] = []
    origins: list[datetime] = []
    targets: list[datetime] = []
    x: list[tuple[float, ...]] = []
    y: list[float] = []
    for subject, observations in sorted(by_subject.items()):
        rows = sorted(observations, key=lambda r: r.start_utc)
        starts = [r.start_utc for r in rows]
        cache: dict[datetime, tuple[float, ...] | None] = {}
        for label in hourly_values(rows, bin_config, training.fit_as_of):
            for lead in range(config.max_lead_hours + 1):
                origin = label.start - lead * HOUR
                if origin not in cache:
                    left = bisect_left(starts, origin - config.lookback_hours * HOUR)
                    right = bisect_left(starts, origin)
                    cache[origin] = _features(rows[left:right], config, origin, origin)
                features = cache[origin]
                if features is not None:
                    phase = label.start.hour * 2 * math.pi / 24
                    x.append((*features[:5], math.sin(phase), math.cos(phase), float(lead)))
                    y.append(label.value)
                    subjects.append(subject)
                    origins.append(origin)
                    targets.append(label.start)
    return TrainingPairs(
        tuple(subjects),
        tuple(origins),
        tuple(targets),
        np.asarray(x, dtype=np.float64).reshape(-1, len(FEATURES)),
        np.asarray(y, dtype=np.float64),
    )


class Projection(Contract):
    mean: tuple[float, ...]
    components: tuple[tuple[float, ...], ...]


class RidgeHeadArtifact(Contract):
    format_version: Literal["encoder-ridge-head-1"] = "encoder-ridge-head-1"
    model_id: str
    config: HeadConfig
    blocks: tuple[str, ...]
    support: tuple[str, ...]
    embedding_sha256: dict[str, Sha256]
    fit_as_of: UtcDatetime
    training_prefix_sha256: Sha256
    training_examples: Annotated[int, Field(ge=1)]
    training_subjects: Annotated[int, Field(ge=1)]
    projections: dict[str, Projection]
    feature_mean: tuple[float, ...]
    feature_scale: tuple[float, ...]
    column_mean: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    label_min: float
    label_max: float

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if not self.blocks or len(set(self.blocks)) != len(self.blocks):
            raise ValueError("a head needs distinct input blocks")
        if set(self.projections) != set(self.blocks) - {HANDCRAFTED}:
            raise ValueError("every embedding block needs exactly one projection")
        if not set(self.blocks) - {HANDCRAFTED} <= set(self.support):
            raise ValueError("embedding blocks must be inside the shared support")
        if len(self.feature_mean) != len(self.feature_scale):
            raise ValueError("feature standardization is inconsistent")
        width = len(self.feature_mean) * (3 if self.config.phase_interactions else 1)
        if len(self.coefficients) != width or len(self.column_mean) != width:
            raise ValueError("coefficients do not match the design width")
        for value in (self.label_min, self.label_max, self.intercept):
            if not math.isfinite(value):
                raise ValueError("non-finite head state")
        return self

    def predictor(self, tables: Mapping[str, EmbeddingTable]) -> Predictor:
        for name, digest in self.embedding_sha256.items():
            if tables[name].sha256 != digest:
                raise ValueError(f"embedding table {name} differs from the one fitted")
        projections = {
            name: (np.asarray(p.mean), np.asarray(p.components))
            for name, p in self.projections.items()
        }
        mean = np.asarray(self.feature_mean)
        scale = np.asarray(self.feature_scale)
        column_mean = np.asarray(self.column_mean)
        coefficients = np.asarray(self.coefficients)
        metric = self.config.tree.metric

        def predict(request: ForecastInput) -> tuple[ForecastEstimate | None, ...]:
            if request.cutoff < self.fit_as_of:
                raise ValueError("prediction cutoff precedes the model's fit cutoff")
            found = {
                name: tables[name].lookup(
                    request.subject_id, request.cutoff, self.config.max_staleness_hours
                )
                for name in self.support
            }
            estimates: list[ForecastEstimate | None] = []
            for target in request.targets:
                hand = _features(
                    request.history, self.config.tree, request.cutoff, target.start_utc
                )
                if hand is None or any(i is None for i in found.values()):
                    estimates.append(None)
                    continue
                parts = []
                for block in self.blocks:
                    if block == HANDCRAFTED:
                        parts.append(np.asarray(hand))
                    else:
                        center, components = projections[block]
                        vector = tables[block].vectors[found[block]].astype(np.float64)
                        parts.append(components @ (vector - center))
                z = (np.concatenate(parts) - mean) / scale
                row = _design(z[None, :], np.asarray([target.start_utc.hour]), self.config)[0]
                value = float((row - column_mean) @ coefficients + self.intercept)
                value = min(max(value, self.label_min), self.label_max)
                check_metric_value(metric, METRICS[metric].unit, value, 3600, "ridge head")
                estimates.append(ForecastEstimate(median=value))
            return tuple(estimates)

        return predict


def _design(z: np.ndarray, hours: np.ndarray, config: HeadConfig) -> np.ndarray:
    if not config.phase_interactions:
        return z
    phase = hours * 2 * math.pi / 24
    return np.concatenate([z, z * np.sin(phase)[:, None], z * np.cos(phase)[:, None]], axis=1)


def _projection(
    table: EmbeddingTable, subjects: set[str], fit_as_of: datetime, k: int
) -> Projection:
    rows = [
        i
        for i, (s, a) in enumerate(zip(table.subject_ids, table.as_of_utc, strict=True))
        if s in subjects and a <= fit_as_of
    ]
    if len(rows) <= k:
        raise ValueError(f"too few training windows to fit {k} components for {table.name}")
    x = table.vectors[rows].astype(np.float64)
    center = x.mean(axis=0)
    _, _, vt = np.linalg.svd(x - center, full_matrices=False)
    return Projection(
        mean=tuple(float(v) for v in center),
        components=tuple(tuple(float(v) for v in row) for row in vt[:k]),
    )


def fit_ridge_head(
    training: TrainingPrefix,
    config: HeadConfig,
    *,
    model_id: str,
    blocks: Sequence[str],
    support: Sequence[str],
    tables: Mapping[str, EmbeddingTable],
    pairs: TrainingPairs | None = None,
) -> RidgeHeadArtifact:
    pairs = pairs if pairs is not None else training_pairs(training, config.tree)
    subjects = set(training.subjects)
    found = {
        name: [
            tables[name].lookup(s, o, config.max_staleness_hours)
            for s, o in zip(pairs.subjects, pairs.origins, strict=True)
        ]
        for name in support
    }
    keep = [i for i in range(len(pairs.labels)) if all(found[n][i] is not None for n in support)]
    if not keep:
        raise ValueError("no training pairs inside the shared embedding support")
    projections = {
        name: _projection(tables[name], subjects, training.fit_as_of, config.pca_components)
        for name in blocks
        if name != HANDCRAFTED
    }
    parts = []
    for block in blocks:
        if block == HANDCRAFTED:
            parts.append(pairs.handcrafted[keep])
        else:
            center = np.asarray(projections[block].mean)
            components = np.asarray(projections[block].components)
            vectors = tables[block].vectors[[found[block][i] for i in keep]].astype(np.float64)
            parts.append((vectors - center) @ components.T)
    raw = np.concatenate(parts, axis=1)
    y = pairs.labels[keep]
    kept_subjects = [pairs.subjects[i] for i in keep]
    counts = Counter(kept_subjects)
    weights = np.asarray([1 / counts[s] for s in kept_subjects])
    weights /= weights.sum()
    mean = weights @ raw
    scale = np.sqrt(weights @ (raw - mean) ** 2)
    scale[scale < 1e-12] = 1.0
    hours = np.asarray([pairs.targets[i].hour for i in keep])
    design = _design((raw - mean) / scale, hours, config)
    column_mean = weights @ design
    centered = design - column_mean
    y_mean = float(weights @ y)
    gram = centered.T @ (centered * weights[:, None])
    coefficients = np.linalg.solve(
        gram + config.ridge_alpha / len(y) * np.eye(gram.shape[0]),
        centered.T @ (weights * (y - y_mean)),
    )
    return RidgeHeadArtifact(
        model_id=model_id,
        config=config,
        blocks=tuple(blocks),
        support=tuple(support),
        embedding_sha256={name: tables[name].sha256 for name in support},
        fit_as_of=training.fit_as_of,
        training_prefix_sha256=document_sha256(training),
        training_examples=len(keep),
        training_subjects=len(counts),
        projections=projections,
        feature_mean=tuple(float(v) for v in mean),
        feature_scale=tuple(float(v) for v in scale),
        column_mean=tuple(float(v) for v in column_mean),
        coefficients=tuple(float(v) for v in coefficients),
        intercept=y_mean,
        label_min=float(y.min()),
        label_max=float(y.max()),
    )


def ridge_head_factory(
    config: HeadConfig,
    *,
    model_id: str,
    blocks: Sequence[str],
    support: Sequence[str],
    tables: Mapping[str, EmbeddingTable],
    pairs_cache: dict[str, TrainingPairs] | None = None,
    fitted: list[RidgeHeadArtifact] | None = None,
) -> PredictorFactory:
    """A factory that fits only from the evaluator's prefix; cached pairs are keyed by its hash."""

    def fit(training: TrainingPrefix) -> Predictor:
        pairs = None
        if pairs_cache is not None:
            key = document_sha256(training)
            pairs = pairs_cache.get(key)
            if pairs is None:
                pairs = pairs_cache[key] = training_pairs(training, config.tree)
        artifact = fit_ridge_head(
            training,
            config,
            model_id=model_id,
            blocks=blocks,
            support=support,
            tables=tables,
            pairs=pairs,
        )
        if fitted is not None:
            fitted.append(artifact)
        return artifact.predictor(tables)

    return fit
