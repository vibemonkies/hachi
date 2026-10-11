"""Causal comparator interfaces; real-cohort performance remains an evaluation gate."""

from .artifacts import load_artifact, save_artifact
from .forecast import (
    BaselineArtifact,
    BaselineConfig,
    baseline_factory,
    fit_baseline,
    hourly_values,
)
from .nightly import NightlyFeaturePolicy, NightlyFeatureResult, NightlyRequest, nightly_rest
from .robust import NightlyRest, RobustConfig, nightly_deviation
from .tree import TreeArtifact, TreeConfig, fit_tree, tree_factory

__all__ = [
    "BaselineArtifact",
    "BaselineConfig",
    "NightlyFeaturePolicy",
    "NightlyFeatureResult",
    "NightlyRequest",
    "NightlyRest",
    "RobustConfig",
    "TreeArtifact",
    "TreeConfig",
    "baseline_factory",
    "fit_baseline",
    "fit_tree",
    "hourly_values",
    "load_artifact",
    "nightly_deviation",
    "nightly_rest",
    "save_artifact",
    "tree_factory",
]
