"""Causal training pairs and data-only tree artifacts; sklearn is needed only to fit."""

import math
from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime
from statistics import fmean
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, Sha256, UtcDatetime
from hachi.contracts.metrics import METRICS, Aggregation, Metric, check_metric_value
from hachi.evaluation import (
    ForecastEstimate,
    ForecastInput,
    ForecastObservation,
    Predictor,
    PredictorFactory,
    TrainingPrefix,
)
from hachi.evaluation.serialization import document_sha256

from .forecast import HOUR, BaselineConfig, hourly_values

FEATURES = (
    "last_value",
    "previous_value",
    "prefix_mean",
    "observed_hours",
    "age_hours",
    "target_sin",
    "target_cos",
    "lead_hours",
)


class TreeConfig(Contract):
    metric: Metric
    aggregation: Aggregation
    lookback_hours: Annotated[int, Field(ge=2)] = 48
    min_history_hours: Annotated[int, Field(ge=2)] = 24
    min_samples_per_hour: Annotated[int, Field(gt=0)] = 1
    max_age_hours: Annotated[int, Field(gt=0)] = 2
    max_lead_hours: Annotated[int, Field(ge=0, le=168)] = 23
    max_depth: Annotated[int, Field(ge=1, le=12)] = 5
    min_samples_leaf: Annotated[int, Field(gt=0)] = 20
    min_training_examples: Annotated[int, Field(gt=0)] = 100
    seed: int = 42

    @model_validator(mode="after")
    def _policy(self) -> Self:
        if self.min_history_hours > self.lookback_hours:
            raise ValueError("minimum history must fit inside lookback")
        if self.aggregation not in METRICS[self.metric].aggregations:
            raise ValueError("tree requires the registered metric aggregation")
        return self


class Leaf(Contract):
    kind: Literal["leaf"] = "leaf"
    value: float


class Branch(Contract):
    kind: Literal["branch"] = "branch"
    feature: Annotated[int, Field(ge=0, lt=len(FEATURES))]
    threshold: float
    left: Annotated[int, Field(ge=0)]
    right: Annotated[int, Field(ge=0)]


type Node = Annotated[Leaf | Branch, Field(discriminator="kind")]


def _features(
    observations: Sequence[ForecastObservation],
    config: TreeConfig,
    cutoff: datetime,
    target: datetime,
) -> tuple[float, ...] | None:
    lead = (target - cutoff).total_seconds() / 3600
    if lead < 0 or lead > config.max_lead_hours or not lead.is_integer():
        return None
    bin_config = BaselineConfig(
        method="last_valid",
        metric=config.metric,
        aggregation=config.aggregation,
        min_samples_per_hour=config.min_samples_per_hour,
    )
    start = cutoff - config.lookback_hours * HOUR
    rows = hourly_values([r for r in observations if r.start_utc >= start], bin_config, cutoff)
    if len(rows) < config.min_history_hours:
        return None
    age = (cutoff - rows[-1].start).total_seconds() / 3600
    if age > config.max_age_hours:
        return None
    phase = target.hour * 2 * math.pi / 24
    return (
        rows[-1].value,
        rows[-2].value,
        fmean(r.value for r in rows),
        float(len(rows)),
        age,
        math.sin(phase),
        math.cos(phase),
        lead,
    )


def _float32(value: float) -> float:
    # sklearn's tree predictor converts features to float32 before comparing.
    # Match that boundary without requiring numpy or executing a pickle at serving.
    import struct

    return struct.unpack("f", struct.pack("f", value))[0]


class TreeArtifact(Contract):
    format_version: Literal["causal-hourly-tree-1"] = "causal-hourly-tree-1"
    model_id: Literal["causal-hourly-tree-v1"] = "causal-hourly-tree-v1"
    config: TreeConfig
    fit_as_of: UtcDatetime
    training_prefix_sha256: Sha256
    training_examples: Annotated[int, Field(ge=0)]
    nodes: Annotated[tuple[Node, ...], Field(max_length=8191)]

    @model_validator(mode="after")
    def _graph(self) -> Self:
        if bool(self.nodes) != (self.training_examples >= self.config.min_training_examples):
            raise ValueError("tree exists exactly when the training inclusion policy is met")
        depths = {0: 0}
        for index, node in enumerate(self.nodes):
            if index not in depths:
                raise ValueError("tree contains unreachable nodes")
            if depths[index] > self.config.max_depth:
                raise ValueError("tree exceeds configured depth")
            if isinstance(node, Branch):
                for child in (node.left, node.right):
                    if not index < child < len(self.nodes) or child in depths:
                        raise ValueError("tree children must be unique forward references")
                    depths[child] = depths[index] + 1
            else:
                check_metric_value(
                    self.config.metric,
                    METRICS[self.config.metric].unit,
                    node.value,
                    3600,
                    "tree leaf",
                )
        return self

    def predict(self, request: ForecastInput) -> tuple[ForecastEstimate | None, ...]:
        if request.cutoff < self.fit_as_of:
            raise ValueError("prediction cutoff precedes the model's fit cutoff")
        estimates: list[ForecastEstimate | None] = []
        for target in request.targets:
            features = _features(request.history, self.config, request.cutoff, target.start_utc)
            if not self.nodes or features is None:
                estimates.append(None)
                continue
            index = 0
            while isinstance(node := self.nodes[index], Branch):
                index = (
                    node.left if _float32(features[node.feature]) <= node.threshold else node.right
                )
            estimates.append(ForecastEstimate(median=node.value))
        return tuple(estimates)


def fit_tree(training: TrainingPrefix, config: TreeConfig) -> TreeArtifact:
    from sklearn.tree import DecisionTreeRegressor

    by_subject: dict[str, list[ForecastObservation]] = defaultdict(list)
    for row in training.observations:
        by_subject[row.subject_id].append(row)
    x: list[tuple[float, ...]] = []
    y: list[float] = []
    subjects: list[str] = []
    bin_config = BaselineConfig(
        method="last_valid",
        metric=config.metric,
        aggregation=config.aggregation,
        min_samples_per_hour=config.min_samples_per_hour,
    )
    for subject, observations in sorted(by_subject.items()):
        rows = sorted(observations, key=lambda r: r.start_utc)
        starts = [r.start_utc for r in rows]
        cache: dict[datetime, tuple[float, ...] | None] = {}
        labels = hourly_values(rows, bin_config, training.fit_as_of)
        for label in labels:
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
    nodes: list[Leaf | Branch] = []
    if len(x) >= config.min_training_examples:
        counts = Counter(subjects)
        estimator = DecisionTreeRegressor(
            max_depth=config.max_depth,
            min_samples_leaf=config.min_samples_leaf,
            random_state=config.seed,
        ).fit(x, y, sample_weight=[1 / counts[s] for s in subjects])
        tree = estimator.tree_
        for index in range(tree.node_count):
            if tree.children_left[index] == -1:
                nodes.append(Leaf(value=float(tree.value[index, 0, 0])))
            else:
                nodes.append(
                    Branch(
                        feature=int(tree.feature[index]),
                        threshold=float(tree.threshold[index]),
                        left=int(tree.children_left[index]),
                        right=int(tree.children_right[index]),
                    )
                )
    return TreeArtifact(
        config=config,
        fit_as_of=training.fit_as_of,
        training_prefix_sha256=document_sha256(training),
        training_examples=len(x),
        nodes=tuple(nodes),
    )


def tree_factory(config: TreeConfig) -> PredictorFactory:
    def fit(training: TrainingPrefix) -> Predictor:
        return fit_tree(training, config).predict

    return fit
