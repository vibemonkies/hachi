from collections import Counter

import pytest
from pydantic import ValidationError

from hachi.contracts.manifests import Exclusion, SplitManifest
from hachi.evaluation import NestedFoldConfig, document_sha256, nested_participant_folds
from hachi.evaluation.splits import rolling_origins


def config(**changes):
    return NestedFoldConfig.model_validate(
        {"outer_folds": 4, "inner_folds": 3, "min_train_subjects": 4, "seed": 42, **changes}
    )


def roster():
    return [f"synthetic-{i}" for i in range(16)]


def test_balanced_outer_and_inner_groups_are_disjoint_complete_and_deterministic():
    subjects = roster()
    plan = nested_participant_folds(subjects, config())
    assert len(plan.folds) == 12
    replay = nested_participant_folds(reversed(subjects), config())
    assert document_sha256(plan) == document_sha256(replay)
    outer_test_counts = Counter()
    for outer in range(4):
        folds = [f for f in plan.folds if f.outer_fold == outer]
        test = set(folds[0].test_subjects)
        outer_test_counts.update(test)
        validation_counts = Counter()
        for fold in folds:
            train, validation = set(fold.train_subjects), set(fold.validation_subjects)
            assert set(fold.test_subjects) == test
            assert not (train & validation or train & test or validation & test)
            assert train | validation | test == set(subjects)
            assert len(train) == 8 and len(validation) == len(test) == 4
            validation_counts.update(validation)
        assert set(validation_counts) == set(subjects) - test
        assert set(validation_counts.values()) == {1}
        refit = plan.outer_partitions(outer)
        assert set(refit["train_subjects"]) == set(subjects) - test
        assert refit["validation_subjects"] == []
    assert set(outer_test_counts) == set(subjects)
    assert set(outer_test_counts.values()) == {1}


def test_exclusions_remain_explicit_and_uneven_groups_remain_balanced():
    exclusions = [
        Exclusion(subject_id="synthetic-0", record_id=None, reason="excluded subject"),
        Exclusion(subject_id="synthetic-1", record_id="source-row", reason="quarantine"),
    ]
    plan = nested_participant_folds(roster(), config(), exclusions=exclusions)
    for fold in plan.folds:
        assert (
            "synthetic-0" not in fold.train_subjects + fold.validation_subjects + fold.test_subjects
        )
        assert list(fold.exclusions) == exclusions
    test_sizes = [len(plan.outer_partitions(i)["test_subjects"]) for i in range(4)]
    assert max(test_sizes) - min(test_sizes) <= 1
    for i in range(4):
        sizes = [len(f.validation_subjects) for f in plan.folds if f.outer_fold == i]
        assert max(sizes) - min(sizes) <= 1
    copied = plan.folds[0].partitions()
    copied["train_subjects"].clear()
    assert plan.folds[0].train_subjects


def test_canonical_manifests_stay_sealed_and_plan_hash_records_fold_choices(
    manifest: SplitManifest,
):
    plan = nested_participant_folds(roster(), config())
    for fold in plan.folds:
        split = SplitManifest.model_validate(
            {
                **manifest.model_dump(),
                **fold.partitions(),
                "fold": fold.outer_fold,
                "n_folds": plan.config.outer_folds,
            }
        )
        with pytest.raises(ValueError, match="sealed"):
            rolling_origins(split, "test")
    assert document_sha256(plan) != document_sha256(
        nested_participant_folds(roster(), config(seed=43))
    )
    with pytest.raises(ValueError, match="does not belong"):
        plan.outer_partitions(99)


@pytest.mark.parametrize(
    "settings",
    [
        {"outer_folds": 17},
        {"inner_folds": 13},
        {"min_train_subjects": 9},
    ],
)
def test_refuse_empty_or_inadequate_training_folds(settings):
    with pytest.raises(ValueError):
        nested_participant_folds(roster(), config(**settings))


def test_roster_and_config_boundaries_refuse_duplicates_unknown_exclusions_and_invalid_counts():
    with pytest.raises(ValueError, match="duplicates"):
        nested_participant_folds([*roster(), roster()[0]], config())
    with pytest.raises(ValueError, match="refer to participants"):
        nested_participant_folds(
            roster(),
            config(),
            exclusions=[Exclusion(subject_id="unknown", record_id=None, reason="unknown")],
        )
    with pytest.raises(ValidationError):
        config(inner_folds=1)
    with pytest.raises(ValidationError):
        config(outer_folds=True)
