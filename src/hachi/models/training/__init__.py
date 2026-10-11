"""#12 training: meta-folds, causal training windows, ridge heads and fine-tune inputs."""

from .meta import MetaPlan, meta_groups, meta_splits
from .ridge import RidgeArtifact, RidgeConfig, fit_ridge, ridge_factory
from .windows import Window, finetune_series, training_windows

__all__ = [
    "MetaPlan",
    "RidgeArtifact",
    "RidgeConfig",
    "Window",
    "finetune_series",
    "fit_ridge",
    "meta_groups",
    "meta_splits",
    "ridge_factory",
    "training_windows",
]
