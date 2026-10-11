"""Grouped meta-folds inside one inner fold's training participants (#12 amendment 1).

Meta-level learners (stacking weights, residual intervals) are fitted only on
out-of-fold predictions made inside the inner fold's training participants, over an
earlier window whose targets all end by the first held-out cutoff. The inner fold's
validation participants and the outer test participants are sealed in every meta
manifest: they are neither fitted on nor scored.
"""

import hashlib
from collections.abc import Iterable
from typing import Annotated, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, UtcDatetime
from hachi.contracts.manifests import SplitManifest, TimeWindow
from hachi.evaluation import NestedFold
from hachi.evaluation.pmdata_run import PMDataProtocol


class MetaPlan(Contract):
    meta_folds: Annotated[int, Field(ge=2)]
    seed: int
    window_start_utc: UtcDatetime
    window_end_utc: UtcDatetime

    @model_validator(mode="after")
    def _window(self) -> Self:
        if self.window_end_utc <= self.window_start_utc:
            raise ValueError("meta window must be nonempty")
        return self


def check_meta_plan(plan: MetaPlan, protocol: PMDataProtocol) -> None:
    """Every meta target must be known by the protocol's first held-out cutoff."""
    if plan.window_end_utc > protocol.evaluation_window.start_utc:
        raise ValueError("meta targets must end by the first held-out cutoff")


def meta_groups(subjects: Iterable[str], plan: MetaPlan, salt: str) -> tuple[tuple[str, ...], ...]:
    """Hash-ranked buckets, independent of data, labels and input order."""
    ranked = sorted(
        subjects, key=lambda s: (hashlib.sha256(f"{plan.seed}:{salt}:{s}".encode()).digest(), s)
    )
    if len(ranked) < plan.meta_folds:
        raise ValueError("each meta-fold needs a held-out participant")
    return tuple(tuple(sorted(ranked[i :: plan.meta_folds])) for i in range(plan.meta_folds))


def meta_splits(
    protocol: PMDataProtocol, fold: NestedFold, plan: MetaPlan
) -> tuple[SplitManifest, ...]:
    """One manifest per meta-fold; validation and outer test participants stay sealed."""
    check_meta_plan(plan, protocol)
    salt = f"meta:{fold.outer_fold}:{fold.inner_fold}"
    sealed = sorted(fold.validation_subjects + fold.test_subjects)
    manifests = []
    for index, held in enumerate(meta_groups(fold.train_subjects, plan, salt)):
        manifests.append(
            SplitManifest(
                schema_version="0.1",
                manifest_id=f"pmdata-outer{fold.outer_fold}-inner{fold.inner_fold}-meta{index}",
                created_at_utc=protocol.split_created_at_utc,
                dataset_snapshot=protocol.expected_snapshot,
                task="physiology_forecast",
                fold=index,
                n_folds=plan.meta_folds,
                train_subjects=sorted(set(fold.train_subjects) - set(held)),
                validation_subjects=list(held),
                test_subjects=sealed,
                exclusions=list(fold.exclusions),
                lookback_hours=protocol.lookback_hours,
                horizon_hours=protocol.horizon_hours,
                embargo_hours=protocol.embargo_hours,
                cutoff_stride_hours=protocol.cutoff_stride_hours,
                min_history_hours=protocol.min_history_hours,
                evaluation_window=TimeWindow(
                    start_utc=plan.window_start_utc, end_utc=plan.window_end_utc
                ),
                seed=protocol.folds.seed,
                test_opened_at_utc=None,
            )
        )
    return tuple(manifests)
