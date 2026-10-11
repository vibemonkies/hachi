"""Explicit nested participant folds, independent of observations and labels."""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated

from pydantic import Field

from hachi.contracts.base import Contract
from hachi.contracts.manifests import Exclusion

from .splits import Partitions, partition_participants


class NestedFoldConfig(Contract):
    outer_folds: Annotated[int, Field(ge=2)]
    inner_folds: Annotated[int, Field(ge=2)]
    min_train_subjects: Annotated[int, Field(ge=1)]
    seed: int


@dataclass(frozen=True)
class NestedFold:
    outer_fold: int
    inner_fold: int
    train_subjects: tuple[str, ...]
    validation_subjects: tuple[str, ...]
    test_subjects: tuple[str, ...]
    exclusions: tuple[Exclusion, ...]

    def partitions(self) -> Partitions:
        """Fresh fields for a canonical SplitManifest; this does not open test."""
        return {
            "train_subjects": list(self.train_subjects),
            "validation_subjects": list(self.validation_subjects),
            "test_subjects": list(self.test_subjects),
            "exclusions": list(self.exclusions),
        }


@dataclass(frozen=True)
class NestedFoldPlan:
    config: NestedFoldConfig
    folds: tuple[NestedFold, ...]

    def outer_partitions(self, outer_fold: int) -> Partitions:
        """Refit fields after inner-only selection, with the same sealed outer test.

        The caller records frozen selection/config hashes before opening this
        outer test. This helper supplies assignments, not proof of selection.
        """
        fold = next((f for f in self.folds if f.outer_fold == outer_fold), None)
        if fold is None:
            raise ValueError("outer fold does not belong to this plan")
        return {
            "train_subjects": sorted(fold.train_subjects + fold.validation_subjects),
            "validation_subjects": [],
            "test_subjects": list(fold.test_subjects),
            "exclusions": list(fold.exclusions),
        }


def _buckets(subjects: Iterable[str], count: int, salt: str) -> tuple[tuple[str, ...], ...]:
    ranked = sorted(subjects, key=lambda s: (hashlib.sha256(f"{salt}:{s}".encode()).digest(), s))
    return tuple(tuple(sorted(ranked[i::count])) for i in range(count))


def nested_participant_folds(
    subjects: Iterable[str], config: NestedFoldConfig, *, exclusions: Iterable[Exclusion] = ()
) -> NestedFoldPlan:
    """Each participant tests once outside, validates once per eligible outer fold.

    Whole-subject exclusions leave every partition; record exclusions travel with
    every manifest. Hash ranking is input-order independent; buckets differ in size
    by at most one. No data value, episode label, or performance informs assignment.
    """
    initial = partition_participants(
        subjects, seed=config.seed, validation_count=0, test_count=0, exclusions=exclusions
    )
    eligible = set(initial["train_subjects"])
    if config.outer_folds > len(eligible):
        raise ValueError("outer folds must each contain a test participant")
    outer = _buckets(eligible, config.outer_folds, f"nested-outer:{config.seed}")
    folds: list[NestedFold] = []
    for outer_index, test in enumerate(outer):
        development = eligible - set(test)
        if config.inner_folds > len(development):
            raise ValueError("inner folds must each contain a validation participant")
        inner = _buckets(
            development, config.inner_folds, f"nested-inner:{config.seed}:{outer_index}"
        )
        for inner_index, validation in enumerate(inner):
            train = tuple(sorted(development - set(validation)))
            if len(train) < config.min_train_subjects:
                raise ValueError("nested fold violates the declared minimum training cohort")
            folds.append(
                NestedFold(
                    outer_index,
                    inner_index,
                    train,
                    validation,
                    test,
                    tuple(initial["exclusions"]),
                )
            )
    return NestedFoldPlan(config, tuple(folds))
